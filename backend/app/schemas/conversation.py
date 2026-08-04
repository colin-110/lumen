from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.conversation import MessageRole


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    sources: list[Any]
    cached: bool
    latency_ms: int | None = None
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = []


class ConversationCreate(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None


class ChatSource(BaseModel):
    filename: str
    document_id: str | None = None
    chunk_id: str | None = None
    score: float
    snippet: str


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: str
    sources: list[ChatSource]
    cached: bool = False
    latency_ms: int
