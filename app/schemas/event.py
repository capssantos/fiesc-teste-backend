import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | str | None = None
    source_event_id: str | None = None
    created_at: datetime | None = None
    z_rms_velocity_in_s: float | None = None
    z_rms_velocity_mm_s: float | None = None
    temperature_f: float | None = None
    temperature_c: float | None = None
    x_rms_velocity_in_s: float | None = None
    x_rms_velocity_mm_s: float | None = None
    z_peak_acceleration_g: float | None = None
    x_peak_acceleration_g: float | None = None
    z_peak_vel_comp_freq_hz: float | None = None
    x_peak_vel_comp_freq_hz: float | None = None
    z_rms_acceleration_g: float | None = None
    x_rms_acceleration_g: float | None = None
    z_kurtosis: float | None = None
    x_kurtosis: float | None = None
    z_crest_factor: float | None = None
    x_crest_factor: float | None = None
    z_peak_velocity_in_s: float | None = None
    z_peak_velocity_mm_s: float | None = None
    x_peak_velocity_in_s: float | None = None
    x_peak_velocity_mm_s: float | None = None
    z_high_freq_rms_accel_g: float | None = None
    x_high_freq_rms_accel_g: float | None = None
    fault: str | None = None
    rpm: float | None = None

    @field_validator("id", "source_event_id", mode="before")
    @classmethod
    def normalize_event_identifiers(cls, value: Any) -> Any:
        if value is None:
            return value

        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None

        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return int(value)
            return value

        return str(value).strip()

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_created_at(cls, value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value

        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return None

        normalized = raw.replace("/", "-")
        normalized = re.sub(r"\s*:\s*", ":", normalized)
        normalized = re.sub(r"\s*([+-])\s*", r"\1", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        normalized = normalized.replace("Z", "+00:00")

        if len(normalized) > 10 and normalized[10].isdigit():
            normalized = f"{normalized[:10]}T{normalized[10:]}"

        if len(normalized) > 10 and normalized[10] == " ":
            normalized = f"{normalized[:10]}T{normalized[11:]}"

        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            return datetime.strptime(normalized, "%Y-%m-%d")

        if re.fullmatch(r".*[+-]\d{4}$", normalized):
            normalized = f"{normalized[:-2]}:{normalized[-2:]}"

        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue

        return normalized

    @property
    def resolved_source_event_id(self) -> str | None:
        if self.source_event_id is not None:
            return self.source_event_id
        if self.id is None:
            return None
        return str(self.id)

    @model_validator(mode="after")
    def validate_metrics(self) -> "EventAnalyzeRequest":
        payload = self.model_dump(exclude={"id", "source_event_id", "created_at", "fault"})
        if not any(value is not None for value in payload.values()):
            raise ValueError("At least one metric field must be provided.")
        return self


class EventClassification(BaseModel):
    status: str
    state: str | None = None
    probable_fault: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class SimilarityBlock(BaseModel):
    status: str
    k: int
    neighbors: list[dict[str, Any]] = Field(default_factory=list)


class EventAnalyzeResponse(BaseModel):
    analysis_id: UUID
    event: dict[str, Any]
    classification: EventClassification
    similarity: SimilarityBlock
    history: dict[str, Any] = Field(default_factory=dict)
    documentation: dict[str, Any] = Field(default_factory=dict)
    recommendation: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class SimilarEventsResponse(BaseModel):
    status: str
    event: dict[str, Any]
    k: int
    neighbors: list[dict[str, Any]] = Field(default_factory=list)
