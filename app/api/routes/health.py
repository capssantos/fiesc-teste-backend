from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentChunkRecord, DocumentRecord
from app.db.session import get_db
from app.schemas.health import HealthResponse
from app.services.object_storage import check_storage_health
from app.services.similarity_engine import similarity_engine_health


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    database_status = "down"
    indexed_document_count = 0
    document_chunk_count = 0
    try:
        db.execute(text("SELECT 1"))
        database_status = "up"
        indexed_document_count = db.scalar(select(func.count()).select_from(DocumentRecord).where(DocumentRecord.status == "indexed")) or 0
        document_chunk_count = db.scalar(select(func.count()).select_from(DocumentChunkRecord)) or 0
    except Exception:
        database_status = "down"

    return HealthResponse(
        api="up",
        database=database_status,
        object_storage=check_storage_health(),
        similarity_index=similarity_engine_health(),
        document_index="indexed" if document_chunk_count else "mapped" if Path(settings.fault_document_map_path).exists() else "missing",
        fault_document_map="loaded" if Path(settings.fault_document_map_path).exists() else "missing",
        llm="configured" if settings.llm_configured else "llm_not_configured",
        llm_provider=settings.effective_llm_provider,
        openai_model=settings.openai_model,
        openai_api_key_present=bool(settings.openai_api_key),
        indexed_document_count=indexed_document_count,
        document_chunk_count=document_chunk_count,
    )
