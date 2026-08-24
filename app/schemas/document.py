from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    storage_uri: str
    bucket: str | None = None
    object_key: str | None = None
    download_url: str | None = None
    fault: str | None = None
    status: str
    metadata_json: dict[str, Any] | None = None
    created_at: datetime


class DocumentUploadResponse(BaseModel):
    document: DocumentItem
    message: str
