"""Retrieval pipeline debugger.

Exposes every intermediate stage of the chat pipeline for one question —
query rewrite, semantic-cache check, dense/sparse/fused/reranked candidates,
the chunks actually selected, and the exact prompt the LLM receives.

Superuser-only: the response includes the system prompt and the raw
retrieved chunk text, which regular users have no reason to see.

Retrieval stages run entirely locally (embeddings + Qdrant), so this costs
nothing to call. The two paid steps are opt-in: query rewriting only runs
when `conversation_id` is set, and answer generation only when
`generate_answer` is true.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.crud.crud_conversation import conversation as crud_conversation
from app.db.session import get_db
from app.models.user import User
from app.schemas.debug import (
    DebugChunk,
    DebugStage,
    RetrievalDebugRequest,
    RetrievalDebugResponse,
)
from app.services import retrieval, semantic_cache

# Private helpers imported deliberately: a debugger that reconstructed the
# prompt or source formatting itself would drift from what chat really sends,
# which defeats the point of inspecting it.
from app.services.agent import (
    ChatMessage,
    _build_sources,
    _format_context,
    _rewrite_query,
    _system_prompt_for,
)
from app.services.llm_router import MODEL_ALIAS, get_router

router = APIRouter()

STAGE_LIMIT = 10


def _to_chunks(raw, previous: list[DebugChunk] | None) -> list[DebugChunk]:
    prior_rank = {c.chunk_id: c.rank for c in (previous or [])}
    return [
        DebugChunk(
            rank=i,
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            filename=c.filename,
            snippet=c.text[:600],
            score=round(c.score, 4),
            previous_rank=prior_rank.get(c.chunk_id),
        )
        for i, c in enumerate(raw, start=1)
    ]


@router.post("/retrieval", response_model=RetrievalDebugResponse)
async def debug_retrieval(
    request: RetrievalDebugRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    started = time.perf_counter()
    org_str = str(current_user.organization_id) if current_user.organization_id else None
    owner_str = str(current_user.id)
    doc_ids = [str(d) for d in request.document_ids] if request.document_ids else None

    # --- 1. query rewrite (only with conversation history) -----------------
    history: list[ChatMessage] = []
    if request.conversation_id:
        convo = await crud_conversation.get_for_user(
            db, id=request.conversation_id, user_id=current_user.id, with_messages=True
        )
        if convo:
            history = [ChatMessage(role=m.role.value, content=m.content) for m in convo.messages]

    search_query = await _rewrite_query(request.message, history)
    rewrite_applied = search_query.strip() != request.message.strip()

    # --- 2. semantic cache probe -------------------------------------------
    cached = await semantic_cache.lookup(search_query, org_str, owner_str)
    if not settings.SEMANTIC_CACHE_ENABLED:
        cache_note = "Semantic cache is disabled (SEMANTIC_CACHE_ENABLED=false)."
    elif cached is not None:
        cache_note = (
            f"A cached answer above the {settings.SEMANTIC_CACHE_THRESHOLD} similarity threshold exists — "
            "production chat would return it and skip retrieval and generation entirely."
        )
    else:
        cache_note = (
            f"No cached answer within the {settings.SEMANTIC_CACHE_THRESHOLD} similarity threshold; "
            "the full retrieve-and-generate path runs."
        )

    # --- 3. retrieval stages ------------------------------------------------
    stages: list[DebugStage] = []

    async def add_stage(key: str, label: str, description: str, fn, previous: list[DebugChunk] | None):
        """Runs one stage, records its timing and rank deltas, and hands back
        both the raw chunks (for downstream reuse) and their debug view."""
        t0 = time.perf_counter()
        raw = await fn()
        elapsed = (time.perf_counter() - t0) * 1000
        chunks = _to_chunks(raw, previous)
        stages.append(
            DebugStage(key=key, label=label, description=description, duration_ms=round(elapsed, 1), chunks=chunks)
        )
        return raw, chunks

    await add_stage(
        "dense",
        "Dense vector search",
        f"Top {STAGE_LIMIT} by cosine similarity on {settings.DENSE_MODEL} embeddings. Catches semantic "
        "matches even when no words overlap.",
        lambda: retrieval.dense_search(search_query, org_str, owner_str, STAGE_LIMIT, doc_ids),
        None,
    )
    await add_stage(
        "sparse",
        "Sparse / BM25 search",
        f"Top {STAGE_LIMIT} by {settings.SPARSE_MODEL} term matching. Catches exact identifiers "
        "(error codes, part numbers) that dense embeddings blur together.",
        lambda: retrieval.sparse_search(search_query, org_str, owner_str, STAGE_LIMIT, doc_ids),
        None,
    )
    _, fused = await add_stage(
        "fused",
        "RRF fusion",
        "Both result lists merged by Reciprocal Rank Fusion — rank-based, so the two scoring scales "
        "never need to be normalised against each other.",
        lambda: retrieval.hybrid_search_no_rerank(search_query, org_str, owner_str, STAGE_LIMIT, doc_ids),
        None,
    )
    _, reranked = await add_stage(
        "reranked",
        "Cross-encoder rerank",
        f"{settings.RERANK_MODEL} scores each candidate against the query jointly, rather than comparing "
        "two independently-computed vectors. This is the step that fixes fusion's ordering.",
        lambda: retrieval.hybrid_search_reranked(search_query, org_str, owner_str, STAGE_LIMIT, doc_ids),
        fused,
    )
    selected_description = (
        f"Scoped to {len(doc_ids)} pinned document(s): the {settings.RERANK_TOP_K}-chunk budget is "
        "filled round-robin so every pinned document contributes its best chunk before any "
        "contributes a second — otherwise a long document crowds a short one out of the comparison."
        if doc_ids
        else (
            f"Production cut: keep rerank score >= {settings.MIN_RERANK_SCORE}, take at most "
            f"{settings.RERANK_TOP_K}. If the floor removes everything, the best "
            f"{settings.MIN_CONTEXT_CHUNKS} are kept anyway so the model still has something "
            "to reason from."
        )
    )
    selected_raw, _ = await add_stage(
        "selected",
        "Selected for the prompt",
        selected_description,
        lambda: retrieval.hybrid_search(search_query, org_str, owner_str, doc_ids),
        reranked,
    )

    # --- 4. the exact prompt the model receives -----------------------------
    sources = _build_sources(selected_raw)
    context = _format_context(selected_raw)
    user_turn = f"CONTEXT:\n{context}\n\nQUESTION:\n{request.message}"
    # Resolved exactly the way chat resolves it, so a multi-document trace
    # shows the cross-document instructions the model will actually receive.
    system_prompt = _system_prompt_for(sources)
    final_prompt = f"[system]\n{system_prompt}\n\n[user]\n{user_turn}"

    # --- 5. optional generation ---------------------------------------------
    answer: str | None = None
    if request.generate_answer:
        resp = await get_router().acompletion(
            model=MODEL_ALIAS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_turn},
            ],
            stream=False,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        answer = (resp.choices[0].message.content or "").strip()

    return RetrievalDebugResponse(
        question=request.message,
        rewritten_query=search_query,
        rewrite_applied=rewrite_applied,
        cache_hit=cached is not None,
        cache_note=cache_note,
        stages=stages,
        final_prompt=final_prompt,
        answer=answer,
        total_ms=round((time.perf_counter() - started) * 1000, 1),
    )
