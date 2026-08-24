import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentRecord
from app.db.session import get_db
from app.schemas.document import DocumentItem, DocumentUploadResponse
from app.services.document_storage import sanitize_filename, validate_extension
from app.services.fault_map import get_fault_entry
from app.services.object_storage import generate_download_url, upload_bytes


router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentItem])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentItem]:
    records = db.scalars(select(DocumentRecord).order_by(DocumentRecord.created_at.desc())).all()
    response: list[DocumentItem] = []
    for record in records:
        metadata = record.metadata_json or {}
        bucket = metadata.get("bucket")
        object_key = metadata.get("object_key")
        download_url = None
        if bucket and object_key:
            download_url = generate_download_url(bucket=bucket, object_key=object_key, response_filename=record.filename)
        response.append(
            DocumentItem(
                id=record.id,
                filename=record.filename,
                storage_uri=record.stored_path,
                bucket=bucket,
                object_key=object_key,
                download_url=download_url,
                fault=record.fault,
                status=record.status,
                metadata_json=metadata,
                created_at=record.created_at,
            )
        )
    return response


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    canonical_fault: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    filename = file.filename or "document.bin"
    validate_extension(filename, settings.allowed_extensions)

    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file_too_large")

    safe_name = sanitize_filename(filename)
    object_key = f"documents/{uuid.uuid4()}_{safe_name}"

    upload_bytes(
        bucket=settings.s3_documents_bucket,
        object_key=object_key,
        data=content,
        content_type=file.content_type or "application/octet-stream",
    )

    resolved_fault = None
    if canonical_fault:
        entry = get_fault_entry(canonical_fault)
        resolved_fault = entry["canonical_label"] if entry else canonical_fault

    record = DocumentRecord(
        filename=safe_name,
        stored_path=f"s3://{settings.s3_documents_bucket}/{object_key}",
        fault=resolved_fault,
        status="uploaded",
        metadata_json={
            "content_type": file.content_type,
            "size_bytes": len(content),
            "original_filename": filename,
            "bucket": settings.s3_documents_bucket,
            "object_key": object_key,
        },
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return DocumentUploadResponse(
        document=DocumentItem(
            id=record.id,
            filename=record.filename,
            storage_uri=record.stored_path,
            bucket=settings.s3_documents_bucket,
            object_key=object_key,
            download_url=generate_download_url(
                bucket=settings.s3_documents_bucket,
                object_key=object_key,
                response_filename=record.filename,
            ),
            fault=record.fault,
            status=record.status,
            metadata_json=record.metadata_json,
            created_at=record.created_at,
        ),
        message="Document uploaded and stored in object storage.",
    )
