from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import AnalysisRecord
from app.db.session import get_db
from app.schemas.analysis import AnalysisDetailResponse, AnalysisHistoryResponse, AnalysisListItem
from app.schemas.event import EventAnalyzeResponse
from app.services.similarity_engine import get_similarity_engine


router = APIRouter(prefix="/analyses", tags=["analyses"])


def _stored_result(analysis: AnalysisRecord) -> dict[str, Any] | None:
    evidence = analysis.evidence_json or {}
    result = evidence.get("response_payload")
    return result if isinstance(result, dict) else None


def _analysis_result(analysis: AnalysisRecord, db: Session, include_recommendation: bool = True) -> dict[str, Any]:
    stored = _stored_result(analysis)
    if stored:
        return stored

    if analysis.event is None:
        raise HTTPException(status_code=404, detail="Analysis event not found.")

    result = get_similarity_engine().find_similar(
        analysis.event.payload_json,
        db=db,
        include_recommendation=include_recommendation,
    )
    return {
        "analysis_id": str(analysis.id),
        "event": analysis.event.payload_json,
        "classification": {
            "status": analysis.status,
            "state": analysis.probable_state,
            "probable_fault": analysis.probable_fault,
            "evidence": analysis.evidence_json or result["classification"].get("evidence", {}),
        },
        "similarity": result["similarity"],
        "history": result["history"],
        "documentation": result["documentation"],
        "recommendation": result["recommendation"],
        "artifacts": (analysis.evidence_json or {}).get("artifacts", {}),
    }


def _summary_item(analysis: AnalysisRecord, db: Session) -> AnalysisListItem:
    result = _analysis_result(analysis, db, include_recommendation=False)
    return AnalysisListItem(
        analysis_id=analysis.id,
        event_id=analysis.event_id,
        source_event_id=analysis.event.source_event_id if analysis.event else None,
        fault_label=analysis.event.fault_label if analysis.event else None,
        probable_fault=analysis.probable_fault,
        probable_state=analysis.probable_state,
        status=analysis.status,
        neighbor_count=analysis.neighbor_count,
        created_at=analysis.created_at,
        history=result.get("history") or {},
        similarity=result.get("similarity") or {},
    )


@router.get("", response_model=AnalysisHistoryResponse)
def list_analyses(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> AnalysisHistoryResponse:
    records = db.scalars(
        select(AnalysisRecord)
        .options(joinedload(AnalysisRecord.event))
        .order_by(AnalysisRecord.created_at.desc())
        .limit(limit)
    ).all()
    return AnalysisHistoryResponse(items=[_summary_item(record, db) for record in records])


@router.get("/latest", response_model=AnalysisDetailResponse)
def latest_analysis(db: Session = Depends(get_db)) -> AnalysisDetailResponse:
    record = db.scalar(
        select(AnalysisRecord)
        .options(joinedload(AnalysisRecord.event))
        .order_by(AnalysisRecord.created_at.desc())
        .limit(1)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="No analyses found.")

    result = _analysis_result(record, db)
    return AnalysisDetailResponse(**result, created_at=record.created_at)


@router.get("/{analysis_id}", response_model=AnalysisDetailResponse)
def analysis_detail(analysis_id: UUID, db: Session = Depends(get_db)) -> AnalysisDetailResponse:
    record = db.scalar(
        select(AnalysisRecord)
        .options(joinedload(AnalysisRecord.event))
        .where(AnalysisRecord.id == analysis_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    result = _analysis_result(record, db)
    return AnalysisDetailResponse(**result, created_at=record.created_at)
