from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.event import EventAnalyzeResponse


class AnalysisListItem(BaseModel):
    analysis_id: UUID
    event_id: UUID
    source_event_id: str | None = None
    fault_label: str | None = None
    probable_fault: str | None = None
    probable_state: str | None = None
    status: str
    neighbor_count: int
    created_at: datetime
    history: dict[str, Any] = Field(default_factory=dict)
    similarity: dict[str, Any] = Field(default_factory=dict)


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisListItem] = Field(default_factory=list)


class AnalysisDetailResponse(EventAnalyzeResponse):
    created_at: datetime | None = None
