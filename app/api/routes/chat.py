from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AnalysisRecord
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.recommendation import build_recommendation_for_fault


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def contextual_chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    target_fault = payload.fault

    if payload.analysis_id and target_fault is None:
        analysis = db.get(AnalysisRecord, payload.analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis not found.")
        target_fault = analysis.probable_fault

    if not target_fault:
        return ChatResponse(
            status="invalid_input",
            recommendation_available=False,
            fault=None,
            message="Provide analysis_id or fault context.",
            sources=[],
            context_chunks=[],
            answer={},
        )

    result = build_recommendation_for_fault(target_fault, payload.message)
    return ChatResponse(
        status=result["status"],
        recommendation_available=result["recommendation_available"],
        fault=result.get("fault", target_fault),
        message=result.get("message") or result.get("summary") or "Resposta gerada.",
        sources=result.get("sources", []),
        context_chunks=result.get("context_chunks", []),
        answer=result,
    )
