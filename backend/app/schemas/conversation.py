from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
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
    title: str | None = Field(None, max_length=255)


class ChatRequest(BaseModel):
    # Bounded because the question is concatenated with retrieved context to
    # build the prompt: an unbounded question is an unbounded bill and a
    # guaranteed context-window error, discovered at the provider instead of
    # at the edge.
    message: str = Field(..., min_length=1, max_length=settings.MAX_MESSAGE_CHARS)
    conversation_id: uuid.UUID | None = None
    # Pin the answer to specific documents (e.g. "does this invoice match this
    # contract?"). Retrieval is restricted to them and the context budget is
    # split fairly across them, so a long document can't crowd out a short one.
    # Omit to search everything, which stays the default.
    document_ids: list[uuid.UUID] | None = Field(None, max_length=settings.MAX_PINNED_DOCUMENTS)


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
