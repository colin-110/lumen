from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentCreate(BaseModel):
    id: uuid.UUID | None = None
    filename: str
    file_type: str
    file_size: int
    storage_key: str
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    status: DocumentStatus = DocumentStatus.PENDING


class DocumentUpdate(BaseModel):
    status: DocumentStatus | None = None
    error_message: str | None = None
    chunk_count: int | None = None
    doc_metadata: dict[str, Any] | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
