from __future__ import annotations

import uuid

from pydantic import BaseModel


class DebugChunk(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    filename: str
    snippet: str
    score: float
    # Rank this same chunk held in the previous stage, or None if it wasn't
    # there at all. This is what makes the reranker's effect visible: a chunk
    # that was 8th after fusion and 1st after reranking shows `previous_rank: 8`.
    previous_rank: int | None = None


class DebugStage(BaseModel):
    key: str
    label: str
    description: str
    duration_ms: float
    chunks: list[DebugChunk]


class RetrievalDebugRequest(BaseModel):
    message: str
    # Optional: fold this conversation's history into a standalone query first,
    # exactly as production chat does. Costs one LLM call when set.
    conversation_id: uuid.UUID | None = None
    # Off by default — the retrieval stages are all local/free, but generating
    # the answer spends provider quota.
    generate_answer: bool = False


class RetrievalDebugResponse(BaseModel):
    question: str
    rewritten_query: str
    rewrite_applied: bool
    cache_hit: bool
    cache_note: str
    stages: list[DebugStage]
    final_prompt: str
    answer: str | None = None
    total_ms: float
