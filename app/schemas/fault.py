from typing import Any

from pydantic import BaseModel, Field


class FaultItem(BaseModel):
    canonical_key: str
    canonical_label: str
    kind: str
    recommendation_supported: bool
    documents: list[str] = Field(default_factory=list)
    candidate_documents: list[str] = Field(default_factory=list)


class FaultDetailResponse(FaultItem):
    raw_labels: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
