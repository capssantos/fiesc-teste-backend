from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.core.config import settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_key: str
    storage_uri: str
    download_url: str


@lru_cache
def get_s3_client():
    if not settings.storage_configured:
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _require_client():
    client = get_s3_client()
    if client is None:
        raise HTTPException(status_code=503, detail="object_storage_not_configured")
    return client


def _replace_with_public_base(url: str) -> str:
    if not settings.s3_public_base_url:
        return url
    original = urlsplit(url)
    public = urlsplit(settings.s3_public_base_url.rstrip("/"))
    query = urlencode(parse_qsl(original.query, keep_blank_values=True))
    return urlunsplit((public.scheme, public.netloc, original.path, query, ""))


def ensure_bucket(bucket: str) -> None:
    client = _require_client()
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code not in {"404", "NoSuchBucket", "NotFound"} and status_code != 404:
            if status_code in {401, 403} or error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from exc
            raise HTTPException(status_code=503, detail="object_storage_unavailable") from exc

        create_kwargs = {"Bucket": bucket}
        if settings.s3_region and settings.s3_region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.s3_region}
        try:
            client.create_bucket(**create_kwargs)
        except ClientError as create_exc:
            create_error_code = str(create_exc.response.get("Error", {}).get("Code", ""))
            create_status_code = create_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if create_status_code in {401, 403} or create_error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from create_exc
            raise HTTPException(status_code=503, detail="object_storage_bucket_create_failed") from create_exc


def ensure_buckets() -> None:
    if not settings.storage_configured:
        return
    ensure_bucket(settings.s3_documents_bucket)
    ensure_bucket(settings.s3_artifacts_bucket)


def upload_bytes(bucket: str, object_key: str, data: bytes, content_type: str) -> StoredObject:
    client = _require_client()
    ensure_bucket(bucket)
    try:
        client.put_object(Bucket=bucket, Key=object_key, Body=data, ContentType=content_type)
    except (ClientError, BotoCoreError) as exc:
        if isinstance(exc, ClientError):
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code in {401, 403} or error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from exc
        raise HTTPException(status_code=503, detail="object_storage_upload_failed") from exc

    return StoredObject(
        bucket=bucket,
        object_key=object_key,
        storage_uri=f"s3://{bucket}/{object_key}",
        download_url=generate_download_url(bucket=bucket, object_key=object_key),
    )


def download_bytes(bucket: str, object_key: str) -> bytes:
    client = _require_client()
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()
    except (ClientError, BotoCoreError) as exc:
        if isinstance(exc, ClientError):
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code in {401, 403} or error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from exc
        raise HTTPException(status_code=503, detail="object_storage_unavailable") from exc


def delete_object(bucket: str, object_key: str) -> None:
    client = _require_client()
    try:
        client.delete_object(Bucket=bucket, Key=object_key)
    except (ClientError, BotoCoreError) as exc:
        if isinstance(exc, ClientError):
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code in {401, 403} or error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from exc
        raise HTTPException(status_code=503, detail="object_storage_unavailable") from exc


def generate_download_url(bucket: str, object_key: str, response_filename: str | None = None) -> str:
    client = _require_client()
    params = {"Bucket": bucket, "Key": object_key}
    if response_filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{response_filename}"'
    try:
        url = client.generate_presigned_url("get_object", Params=params, ExpiresIn=settings.s3_presigned_expiry_seconds)
    except (ClientError, BotoCoreError) as exc:
        if isinstance(exc, ClientError):
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code in {401, 403} or error_code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise HTTPException(status_code=503, detail="object_storage_access_denied") from exc
        raise HTTPException(status_code=503, detail="object_storage_presign_failed") from exc
    return _replace_with_public_base(url)


def check_storage_health() -> str:
    if not settings.storage_configured:
        return "not_configured"
    client = get_s3_client()
    try:
        client.list_buckets()
        return "up"
    except Exception:
        return "down"
