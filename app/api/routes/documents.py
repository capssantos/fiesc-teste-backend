import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT
from app.core.config import settings
from app.db.models import DocumentChunkRecord, DocumentRecord
from app.db.session import get_db
from app.schemas.document import DocumentDeleteResponse, DocumentItem, DocumentReindexResponse, DocumentUploadResponse
from app.services.document_storage import sanitize_filename, validate_extension
from app.services.fault_map import get_fault_entry, load_fault_map
from app.services.object_storage import upload_bytes
from app.services.rag_index import (
    calculate_content_hash,
    delete_document_from_index,
    document_download_url,
    index_document_content,
    reindex_document,
    seed_bundled_rag_documents,
)


router = APIRouter(prefix="/documents", tags=["documents"])


def _resolve_rag_document_path(document_path: str) -> Path:
    path = Path(document_path)
    if path.is_absolute():
        return path
    return BACKEND_ROOT / path


def _document_item(request: Request, record: DocumentRecord) -> DocumentItem:
    metadata = record.metadata_json or {}
    return DocumentItem(
        id=record.id,
        filename=record.filename,
        storage_uri=record.stored_path,
        bucket=metadata.get("bucket"),
        object_key=metadata.get("object_key"),
        download_url=document_download_url(request.url_for, record),
        fault=record.fault,
        status=record.status,
        metadata_json=metadata,
        created_at=record.created_at,
        source=record.source,
        external_id=record.external_id,
        content_hash=record.content_hash,
        indexed_at=record.indexed_at,
    )


@router.get("", response_model=list[DocumentItem])
def list_documents(request: Request, db: Session = Depends(get_db)) -> list[DocumentItem]:
    try:
        records = db.scalars(
            select(DocumentRecord)
            .where(DocumentRecord.status != "deleted")
            .order_by(DocumentRecord.source, DocumentRecord.created_at.desc())
        ).all()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": "Banco de dados indisponivel para listar documentos.",
            },
        ) from exc

    return [_document_item(request, record) for record in records]


@router.get("/rag/{document_id}/download", name="download_rag_document")
def download_rag_document(document_id: str) -> FileResponse:
    document_data = load_fault_map().get("documents", {}).get(document_id)
    if not document_data:
        raise HTTPException(status_code=404, detail="Document not found.")

    document_path = str(document_data.get("path") or "")
    resolved_path = _resolve_rag_document_path(document_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found.")

    return FileResponse(
        path=resolved_path,
        media_type="application/pdf" if resolved_path.suffix.lower() == ".pdf" else None,
        filename=resolved_path.name,
    )


@router.post("/reindex")
def reindex_documents(db: Session = Depends(get_db)) -> dict[str, int]:
    seed_bundled_rag_documents(db)
    records = db.scalars(select(DocumentRecord).where(DocumentRecord.source == "upload")).all()

    reindexed = 0
    failed = 0
    for record in records:
        try:
            reindex_document(db, record)
            reindexed += 1
        except HTTPException:
            failed += 1
            record.status = "index_failed"
            db.commit()

    indexed_documents = db.scalar(select(func.count()).select_from(DocumentRecord).where(DocumentRecord.status == "indexed")) or 0
    document_chunks = db.scalar(select(func.count()).select_from(DocumentChunkRecord)) or 0
    return {
        "indexed_documents": indexed_documents,
        "document_chunks": document_chunks,
        "reindexed_uploads": reindexed,
        "failed_uploads": failed,
    }


@router.post("/{document_id}/reindex", response_model=DocumentReindexResponse)
def reindex_existing_document(document_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> DocumentReindexResponse:
    record = db.get(DocumentRecord, document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    reindex_document(db, record)
    return DocumentReindexResponse(
        document=_document_item(request, record),
        message="Document reindexed.",
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_existing_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentDeleteResponse:
    record = db.get(DocumentRecord, document_id)
    if record is None or record.status == "deleted":
        raise HTTPException(status_code=404, detail="Document not found.")

    storage_deleted = delete_document_from_index(db, record)
    return DocumentDeleteResponse(
        id=document_id,
        status="deleted",
        storage_deleted=storage_deleted,
        message="Document removed from RAG index.",
    )


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
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
        source="upload",
        content_hash=calculate_content_hash(content),
        fault=resolved_fault,
        status="indexing",
        metadata_json={
            "source": "upload",
            "content_type": file.content_type,
            "size_bytes": len(content),
            "original_filename": filename,
            "bucket": settings.s3_documents_bucket,
            "object_key": object_key,
        },
    )
    db.add(record)
    db.flush()
    index_document_content(db, record, content)
    db.commit()
    db.refresh(record)

    return DocumentUploadResponse(
        document=_document_item(request, record),
        message="Document uploaded and stored in object storage.",
    )
