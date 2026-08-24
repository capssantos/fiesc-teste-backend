from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import AnalysisRecord, ChatMessageRecord, ChatSessionRecord
from app.db.session import get_db
from app.schemas.chat import (
    ChatMessageCreateRequest,
    ChatMessageItem,
    ChatRequest,
    ChatResponse,
    ChatSessionCreateRequest,
    ChatSessionDetail,
    ChatSessionItem,
    ChatSessionListResponse,
)
from app.services.recommendation import build_recommendation_for_fault


router = APIRouter(prefix="/chat", tags=["chat"])


def _latest_analysis(db: Session) -> AnalysisRecord | None:
    return db.scalar(select(AnalysisRecord).order_by(AnalysisRecord.created_at.desc()).limit(1))


def _resolve_context(db: Session, analysis_id: UUID | None, fault: str | None) -> tuple[UUID | None, str | None]:
    if analysis_id:
        analysis = db.get(AnalysisRecord, analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis not found.")
        return analysis.id, fault or analysis.probable_fault

    if fault:
        return None, fault

    latest = _latest_analysis(db)
    if latest is None:
        return None, None
    return latest.id, latest.probable_fault


def _session_title(fault: str | None, title: str | None) -> str:
    if title and title.strip():
        return title.strip()[:255]
    return "Nova conversa"


def _title_from_message(message: str) -> str:
    normalized = " ".join(message.strip().split())
    if not normalized:
        return "Nova conversa"

    sentence_end_positions = [
        position for marker in [".", "?", "!"] if (position := normalized.find(marker)) != -1
    ]
    if sentence_end_positions:
        normalized = normalized[: min(sentence_end_positions) + 1]

    if len(normalized) <= 56:
        return normalized
    return f"{normalized[:53].rstrip()}..."


def _is_default_title(title: str) -> bool:
    return title == "Nova conversa" or title.startswith("Conversa sobre ")


def _message_item(message: ChatMessageRecord) -> ChatMessageItem:
    return ChatMessageItem(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        payload_json=message.payload_json,
        created_at=message.created_at,
    )


def _session_item(session: ChatSessionRecord, message_count: int | None = None) -> ChatSessionItem:
    last_message = session.messages[-1] if session.messages else None
    return ChatSessionItem(
        id=session.id,
        title=session.title,
        analysis_id=session.analysis_id,
        fault=session.fault,
        status=session.status,
        message_count=message_count if message_count is not None else len(session.messages),
        last_message_preview=_title_from_message(last_message.content) if last_message else None,
        last_message_at=last_message.created_at if last_message else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _session_detail(session: ChatSessionRecord) -> ChatSessionDetail:
    return ChatSessionDetail(
        **_session_item(session).model_dump(),
        messages=[_message_item(message) for message in session.messages],
    )


def _conversation_prompt(session: ChatSessionRecord, current_message: str) -> str:
    previous_messages = session.messages[-10:]
    if not previous_messages:
        return current_message

    lines = ["Historico recente da conversa:"]
    for message in previous_messages:
        role = "Usuario" if message.role == "user" else "Assistente"
        lines.append(f"{role}: {message.content}")
    lines.append(f"Usuario: {current_message}")
    return "\n".join(lines)


def _create_session(db: Session, payload: ChatSessionCreateRequest) -> ChatSessionRecord:
    analysis_id, fault = _resolve_context(db, payload.analysis_id, payload.fault)
    session = ChatSessionRecord(
        title=_session_title(fault, payload.title),
        analysis_id=analysis_id,
        fault=fault,
        status="active",
        metadata_json={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _send_message(db: Session, session: ChatSessionRecord, message_text: str) -> ChatResponse:
    message_text = message_text.strip()
    if not message_text:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    target_fault = session.fault
    if session.analysis_id and not target_fault:
        analysis = db.get(AnalysisRecord, session.analysis_id)
        target_fault = analysis.probable_fault if analysis else None

    user_message = ChatMessageRecord(
        session_id=session.id,
        role="user",
        content=message_text,
        status="completed",
        payload_json={},
    )
    db.add(user_message)
    db.flush()
    if _is_default_title(session.title):
        session.title = _title_from_message(message_text)

    if not target_fault:
        result = {
            "status": "invalid_input",
            "recommendation_available": False,
            "message": "Crie uma sessao com analysis_id ou fault para conversar com contexto.",
            "sources": [],
            "context_chunks": [],
        }
    else:
        result = build_recommendation_for_fault(target_fault, _conversation_prompt(session, message_text), db)

    assistant_message_text = result.get("message") or result.get("summary") or "Resposta gerada."
    assistant_message = ChatMessageRecord(
        session_id=session.id,
        role="assistant",
        content=assistant_message_text,
        status=result["status"],
        payload_json=result,
    )
    session.fault = target_fault
    session.updated_at = func.now()
    db.add(assistant_message)
    db.commit()

    db.refresh(session)
    session = db.scalar(
        select(ChatSessionRecord)
        .options(selectinload(ChatSessionRecord.messages))
        .where(ChatSessionRecord.id == session.id)
    ) or session

    return ChatResponse(
        session_id=session.id,
        status=result["status"],
        recommendation_available=result["recommendation_available"],
        fault=result.get("fault", target_fault),
        message=assistant_message_text,
        sources=result.get("sources", []),
        context_chunks=result.get("context_chunks", []),
        answer=result,
        messages=[_message_item(message) for message in session.messages],
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_sessions(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
) -> ChatSessionListResponse:
    records = db.scalars(
        select(ChatSessionRecord)
        .options(selectinload(ChatSessionRecord.messages))
        .where(ChatSessionRecord.status != "deleted")
        .order_by(ChatSessionRecord.updated_at.desc())
        .limit(limit)
    ).all()
    return ChatSessionListResponse(items=[_session_item(record) for record in records])


@router.post("/sessions", response_model=ChatSessionDetail)
def create_session(payload: ChatSessionCreateRequest, db: Session = Depends(get_db)) -> ChatSessionDetail:
    session = _create_session(db, payload)
    return _session_detail(session)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def session_detail(session_id: UUID, db: Session = Depends(get_db)) -> ChatSessionDetail:
    session = db.scalar(
        select(ChatSessionRecord)
        .options(selectinload(ChatSessionRecord.messages))
        .where(ChatSessionRecord.id == session_id, ChatSessionRecord.status != "deleted")
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _session_detail(session)


@router.post("/sessions/{session_id}/messages", response_model=ChatResponse)
def send_session_message(
    session_id: UUID,
    payload: ChatMessageCreateRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    session = db.scalar(
        select(ChatSessionRecord)
        .options(selectinload(ChatSessionRecord.messages))
        .where(ChatSessionRecord.id == session_id, ChatSessionRecord.status != "deleted")
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _send_message(db, session, payload.message)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    session = db.get(ChatSessionRecord, session_id)
    if session is None or session.status == "deleted":
        raise HTTPException(status_code=404, detail="Chat session not found.")
    session.status = "deleted"
    session.updated_at = func.now()
    db.commit()
    return {"status": "deleted", "message": "Chat session removed."}


@router.post("", response_model=ChatResponse)
def contextual_chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    if payload.session_id:
        session = db.scalar(
            select(ChatSessionRecord)
            .options(selectinload(ChatSessionRecord.messages))
            .where(ChatSessionRecord.id == payload.session_id, ChatSessionRecord.status != "deleted")
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found.")
    else:
        session = _create_session(
            db,
            ChatSessionCreateRequest(
                analysis_id=payload.analysis_id,
                fault=payload.fault,
            ),
        )
        session = db.scalar(
            select(ChatSessionRecord)
            .options(selectinload(ChatSessionRecord.messages))
            .where(ChatSessionRecord.id == session.id)
        ) or session

    return _send_message(db, session, payload.message)
