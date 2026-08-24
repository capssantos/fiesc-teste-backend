from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT, settings
from app.db.models import DocumentChunkRecord, DocumentRecord
from app.services.document_retrieval import _tokenize, extract_document_chunks
from app.services.fault_map import load_fault_map
from app.services.object_storage import delete_object, download_bytes, generate_download_url, upload_bytes


def calculate_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def related_faults_for_document(document_id: str) -> list[str]:
    mapping = load_fault_map()
    return [
        entry.get("canonical_label", canonical_key)
        for canonical_key, entry in mapping.get("faults", {}).items()
        if document_id in entry.get("documents", [])
    ]


def index_document_content(db: Session, document: DocumentRecord, data: bytes) -> None:
    document.content_hash = calculate_content_hash(data)
    chunks = extract_document_chunks(document.filename, data)
    db.execute(delete(DocumentChunkRecord).where(DocumentChunkRecord.document_id == document.id))

    for chunk in chunks:
        db.add(
            DocumentChunkRecord(
                document_id=document.id,
                page=chunk["page"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                metadata_json={
                    "source": document.source,
                    "filename": document.filename,
                    "external_id": document.external_id,
                },
            )
        )

    document.indexed_at = datetime.now(timezone.utc)
    document.status = "indexed" if chunks else "index_empty"


def mark_document_index_failed(db: Session, document: DocumentRecord, exc: Exception) -> None:
    metadata = dict(document.metadata_json or {})
    metadata["index_error"] = getattr(exc, "detail", str(exc))
    metadata["index_failed_at"] = datetime.now(timezone.utc).isoformat()
    db.execute(delete(DocumentChunkRecord).where(DocumentChunkRecord.document_id == document.id))
    document.metadata_json = metadata
    document.status = "index_failed"
    document.indexed_at = None
    db.commit()
    db.refresh(document)


def reindex_document(db: Session, document: DocumentRecord) -> bool:
    document.status = "indexing"
    document.indexed_at = None
    db.commit()
    db.refresh(document)

    try:
        metadata = document.metadata_json or {}
        bucket = metadata.get("bucket")
        object_key = metadata.get("object_key")
        if bucket and object_key:
            data = download_bytes(bucket=bucket, object_key=object_key)
        else:
            local_path = metadata.get("path") or document.stored_path
            resolved_path = Path(str(local_path))
            if not resolved_path.is_absolute():
                resolved_path = BACKEND_ROOT / resolved_path
            if not resolved_path.exists() or not resolved_path.is_file():
                raise HTTPException(status_code=404, detail="Document file not found.")
            data = resolved_path.read_bytes()

        index_document_content(db, document, data)
        db.commit()
        db.refresh(document)
        return document.status in {"indexed", "index_empty"}
    except Exception as exc:
        mark_document_index_failed(db, document, exc)
        return False


def seed_bundled_rag_documents(db: Session) -> None:
    mapping = load_fault_map()
    for document_id, document_data in mapping.get("documents", {}).items():
        relative_path = str(document_data.get("path") or "")
        source_path = Path(relative_path)
        if not source_path.is_absolute():
            source_path = BACKEND_ROOT / source_path
        if not source_path.exists() or not source_path.is_file():
            continue

        data = source_path.read_bytes()
        content_hash = calculate_content_hash(data)
        filename = source_path.name
        related_faults = related_faults_for_document(document_id)

        document = db.scalar(
            select(DocumentRecord).where(
                DocumentRecord.source == "rag",
                DocumentRecord.external_id == document_id,
            )
        )
        needs_s3_upload = bool(
            document
            and settings.storage_configured
            and (document.metadata_json or {}).get("storage_status") != "s3"
        )
        if document and document.status == "deleted":
            continue
        if document and document.content_hash == content_hash and document.status == "indexed" and not needs_s3_upload:
            continue

        object_key = f"rag/{document_id}/{content_hash[:12]}_{filename}"
        stored_path = relative_path
        metadata: dict[str, Any] = {
            "source": "rag",
            "document_id": document_id,
            "title": document_data.get("title"),
            "path": relative_path,
            "faults": related_faults,
            "storage_status": "local_only",
        }

        try:
            stored = upload_bytes(
                bucket=settings.s3_documents_bucket,
                object_key=object_key,
                data=data,
                content_type="application/pdf" if source_path.suffix.lower() == ".pdf" else "application/octet-stream",
            )
            stored_path = stored.storage_uri
            metadata.update(
                {
                    "bucket": stored.bucket,
                    "object_key": stored.object_key,
                    "storage_status": "s3",
                }
            )
        except HTTPException as exc:
            metadata["storage_error"] = exc.detail

        if document is None:
            document = DocumentRecord(
                filename=filename,
                stored_path=stored_path,
                source="rag",
                external_id=document_id,
                content_hash=content_hash,
                fault=", ".join(related_faults) if related_faults else None,
                status="indexing",
                metadata_json=metadata,
            )
            db.add(document)
            db.flush()
        else:
            document.filename = filename
            document.stored_path = stored_path
            document.content_hash = content_hash
            document.fault = ", ".join(related_faults) if related_faults else None
            document.status = "indexing"
            document.metadata_json = metadata
            db.flush()

        try:
            index_document_content(db, document, data)
        except Exception as exc:
            mark_document_index_failed(db, document, exc)

    db.commit()


def document_download_url(request_url_for, document: DocumentRecord) -> str | None:
    if document.status == "deleted":
        return None

    metadata = document.metadata_json or {}
    bucket = metadata.get("bucket")
    object_key = metadata.get("object_key")
    if bucket and object_key:
        try:
            return generate_download_url(bucket=bucket, object_key=object_key, response_filename=document.filename)
        except HTTPException:
            return None
    if document.source == "rag" and document.external_id:
        return str(request_url_for("download_rag_document", document_id=document.external_id))
    return None


def delete_document_from_index(db: Session, document: DocumentRecord) -> bool:
    metadata = document.metadata_json or {}
    bucket = metadata.get("bucket")
    object_key = metadata.get("object_key")
    storage_deleted = False

    if bucket and object_key:
        try:
            delete_object(bucket=bucket, object_key=object_key)
            storage_deleted = True
        except HTTPException as exc:
            metadata["delete_storage_error"] = exc.detail

    db.execute(delete(DocumentChunkRecord).where(DocumentChunkRecord.document_id == document.id))
    metadata.update(
        {
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "storage_deleted": storage_deleted,
        }
    )
    document.metadata_json = metadata
    document.status = "deleted"
    document.indexed_at = None
    db.commit()
    return storage_deleted


def retrieve_indexed_document_context(db: Session, documents: list[dict[str, Any]], query: str, top_k: int = 3) -> list[dict[str, Any]]:
    document_ids = [document.get("document_id") for document in documents if document.get("document_id")]
    if not document_ids:
        return []

    records = db.scalars(
        select(DocumentRecord).where(
            DocumentRecord.source == "rag",
            DocumentRecord.external_id.in_(document_ids),
            DocumentRecord.status == "indexed",
        )
    ).all()
    if not records:
        return []

    query_tokens = _tokenize(query)
    scored: list[dict[str, Any]] = []
    for record in records:
        metadata = record.metadata_json or {}
        document_tokens = _tokenize(
            " ".join(
                value
                for value in [
                    record.external_id or "",
                    record.filename,
                    str(metadata.get("title") or ""),
                    record.stored_path,
                ]
                if value
            )
        )
        for chunk in record.chunks:
            chunk_tokens = _tokenize(chunk.text)
            score = len(query_tokens & chunk_tokens) + len(query_tokens & document_tokens)
            if score <= 0:
                continue
            scored.append(
                {
                    "document_id": record.external_id,
                    "filename": record.filename,
                    "path": metadata.get("path") or record.stored_path,
                    "title": metadata.get("title"),
                    "page": chunk.page,
                    "score": score,
                    "text": chunk.text,
                }
            )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]
