from typing import Any
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    session_id: UUID | None = None
    analysis_id: UUID | None = None
    fault: str | None = None
    message: str

    @model_validator(mode="after")
    def validate_context(self) -> "ChatRequest":
        if not self.session_id and not self.analysis_id and not self.fault:
            raise ValueError("Provide session_id, analysis_id or fault.")
        return self


class ChatSessionCreateRequest(BaseModel):
    analysis_id: UUID | None = None
    fault: str | None = None
    title: str | None = None


class ChatMessageCreateRequest(BaseModel):
    message: str


class ChatMessageItem(BaseModel):
    id: UUID
    role: str
    content: str
    status: str
    payload_json: dict[str, Any] | None = None
    created_at: datetime


class ChatSessionItem(BaseModel):
    id: UUID
    title: str
    analysis_id: UUID | None = None
    fault: str | None = None
    status: str
    message_count: int = 0
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(ChatSessionItem):
    messages: list[ChatMessageItem] = Field(default_factory=list)


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionItem] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: UUID | None = None
    status: str
    recommendation_available: bool
    fault: str | None = None
    message: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    context_chunks: list[dict[str, Any]] = Field(default_factory=list)
    answer: dict[str, Any] = Field(default_factory=dict)
    messages: list[ChatMessageItem] = Field(default_factory=list)
