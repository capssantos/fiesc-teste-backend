import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AnalysisRecord, EventRecord
from app.db.session import get_db
from app.schemas.event import EventAnalyzeRequest, EventAnalyzeResponse, EventClassification, SimilarEventsResponse, SimilarityBlock
from app.services.object_storage import generate_download_url, upload_bytes
from app.services.similarity_engine import get_similarity_engine


router = APIRouter(prefix="/events", tags=["events"])


@router.post("/analyze", response_model=EventAnalyzeResponse, status_code=status.HTTP_201_CREATED)
def analyze_event(payload: EventAnalyzeRequest, db: Session = Depends(get_db)) -> EventAnalyzeResponse:
    payload_dict = payload.model_dump(mode="json")
    try:
        analysis_result = get_similarity_engine().find_similar(payload_dict, settings.similarity_k, db)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "similarity_dataset_missing",
                "message": "Dataset de similaridade nao encontrado no backend.",
                "expected_path": str(settings.dataset_path),
            },
        ) from exc

    event = EventRecord(
        source_event_id=payload.resolved_source_event_id,
        fault_label=payload.fault,
        payload_json=payload_dict,
    )
    db.add(event)
    db.flush()

    analysis = AnalysisRecord(
        event_id=event.id,
        probable_fault=analysis_result["classification"].get("probable_fault"),
        probable_state=analysis_result["classification"].get("state"),
        status=analysis_result["classification"]["status"],
        neighbor_count=len(analysis_result["similarity"]["neighbors"]),
        evidence_json=analysis_result["classification"]["evidence"],
    )
    db.add(analysis)
    db.flush()

    request_key = f"events/{event.id}/request_payload.json"
    artifacts: dict[str, object] = {}

    try:
        upload_bytes(
            bucket=settings.s3_artifacts_bucket,
            object_key=request_key,
            data=json.dumps(payload_dict, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )

        request_url = generate_download_url(
            bucket=settings.s3_artifacts_bucket,
            object_key=request_key,
            response_filename=f"event_{event.id}_request.json",
        )

        artifacts["request_payload"] = {
            "bucket": settings.s3_artifacts_bucket,
            "object_key": request_key,
            "download_url": request_url,
        }
    except HTTPException as exc:
        artifacts["request_payload"] = {
            "status": "object_storage_unavailable",
            "detail": exc.detail,
        }

    response_payload = EventAnalyzeResponse(
        analysis_id=analysis.id,
        event=payload_dict,
        classification=EventClassification(
            status=analysis.status,
            state=analysis.probable_state,
            probable_fault=analysis.probable_fault,
            evidence=analysis.evidence_json or {},
        ),
        similarity=SimilarityBlock(
            status=analysis_result["similarity"]["status"],
            k=analysis_result["similarity"]["k"],
            neighbors=analysis_result["similarity"]["neighbors"],
        ),
        history=analysis_result["history"],
        documentation=analysis_result["documentation"],
        recommendation=analysis_result["recommendation"],
        artifacts=artifacts,
    )

    response_key = f"analyses/{analysis.id}/result.json"
    try:
        upload_bytes(
            bucket=settings.s3_artifacts_bucket,
            object_key=response_key,
            data=json.dumps(response_payload.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )

        result_url = generate_download_url(
            bucket=settings.s3_artifacts_bucket,
            object_key=response_key,
            response_filename=f"analysis_{analysis.id}_result.json",
        )

        response_payload.artifacts["analysis_result"] = {
            "bucket": settings.s3_artifacts_bucket,
            "object_key": response_key,
            "download_url": result_url,
        }

        upload_bytes(
            bucket=settings.s3_artifacts_bucket,
            object_key=response_key,
            data=json.dumps(response_payload.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )
    except HTTPException as exc:
        response_payload.artifacts["analysis_result"] = {
            "status": "object_storage_unavailable",
            "detail": exc.detail,
        }

    analysis.evidence_json = {**(analysis.evidence_json or {}), "artifacts": response_payload.artifacts}
    db.commit()

    return response_payload


@router.post("/similar", response_model=SimilarEventsResponse)
def similar_events(payload: EventAnalyzeRequest, db: Session = Depends(get_db)) -> SimilarEventsResponse:
    try:
        result = get_similarity_engine().find_similar(payload.model_dump(mode="json"), settings.similarity_k, db)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "similarity_dataset_missing",
                "message": "Dataset de similaridade nao encontrado no backend.",
                "expected_path": str(settings.dataset_path),
            },
        ) from exc
    return SimilarEventsResponse(
        status=result["similarity"]["status"],
        event=payload.model_dump(mode="json"),
        k=result["similarity"]["k"],
        neighbors=result["similarity"]["neighbors"],
    )
