from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    analysis_id: UUID | None = None
    fault: str | None = None
    message: str

    @model_validator(mode="after")
    def validate_context(self) -> "ChatRequest":
        if not self.analysis_id and not self.fault:
            raise ValueError("Provide analysis_id or fault.")
        return self


class ChatResponse(BaseModel):
    status: str
    recommendation_available: bool
    fault: str | None = None
    message: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    context_chunks: list[dict[str, Any]] = Field(default_factory=list)
    answer: dict[str, Any] = Field(default_factory=dict)
