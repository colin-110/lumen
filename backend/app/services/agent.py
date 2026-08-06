"""The Lumen pipeline: retrieve -> (optional web fallback) -> generate.

Exposed as a single async generator (`run`) that yields typed events —
`sources` once retrieval finishes, then `token` repeatedly as the LLM
streams, then `done` with timing/cache metadata. Both the SSE endpoint and
the plain JSON endpoint consume the same generator; JSON mode just
concatenates the tokens instead of flushing them individually. One pipeline,
two transports, no duplicated logic.

This intentionally is *not* a ReAct tool-calling loop. A deterministic
retrieve -> generate pass (with one conditional web-search branch) is
faster, cheaper, and far easier to stream and debug than an LLM deciding
tool calls turn by turn — and for a document assistant it covers the actual
use case just as well.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import settings
from app.services import semantic_cache, web_search as web_search_service
from app.services.llm_router import MODEL_ALIAS, get_router
from app.services.retrieval import RetrievedChunk, hybrid_search

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Lumen: a precise, helpful AI assistant that answers \
questions using the organization's internal documents.

Rules:
- Ground every factual claim in the provided CONTEXT when it's relevant. Cite sources inline \
using bracketed numbers like [1], [2] that match the numbered sources given to you.
- If the context does not contain the answer, say so plainly rather than guessing. You may use \
general knowledge to help interpret the question, but be explicit about what came from the \
documents versus general knowledge.
- Be concise and direct. Use short paragraphs or bullet points for multi-part answers.
- Never fabricate a citation number that wasn't given to you.
"""

# Appended only when the context spans more than one document. Without this the
# model tends to answer from whichever document it saw first and quietly ignore
# the rest, which is exactly the failure mode for "does X match Y?" questions.
MULTI_DOCUMENT_GUIDANCE = """
You have been given context from MULTIPLE DIFFERENT DOCUMENTS. When the question
involves comparing, reconciling or combining them:
- Attribute each fact to the document it came from, by citation number.
- State explicitly where the documents AGREE and where they CONFLICT. A
  disagreement in dates, amounts, names or terms is usually the point of the
  question — surface it rather than smoothing it over or picking one silently.
- If a document you would need in order to answer is missing from the context,
  say which one and what it would have to contain, instead of guessing.
"""


@dataclass
class SourceRef:
    index: int
    filename: str
    document_id: str
    chunk_id: str
    score: float
    snippet: str


@dataclass
class PipelineEvent:
    type: Literal["sources", "token", "done", "error"]
    data: Any = None


@dataclass
class ChatMessage:
    role: str
    content: str


RETRIEVAL_CONFIDENCE_FLOOR = 0.0  # rerank scores below this trigger the web-search fallback


def _format_context(sources: list[SourceRef]) -> str:
    if not sources:
        return "No relevant internal documents were found for this question."
    blocks = [f"[{s.index}] (source: {s.filename})\n{s.snippet}" for s in sources]
    return "\n\n".join(blocks)


def _system_prompt_for(sources: list[SourceRef]) -> str:
    """Add cross-document instructions only when they apply, so single-document
    questions aren't paying for prompt tokens telling the model to compare
    things there is nothing to compare against."""
    distinct_documents = {s.document_id for s in sources if s.document_id}
    if len(distinct_documents) > 1:
        return SYSTEM_PROMPT + MULTI_DOCUMENT_GUIDANCE
    return SYSTEM_PROMPT


def _build_sources(chunks: list[RetrievedChunk]) -> list[SourceRef]:
    return [
        SourceRef(
            index=i + 1,
            filename=c.filename,
            document_id=c.document_id,
            chunk_id=c.chunk_id,
            score=round(c.score, 4),
            snippet=c.text[:600],
        )
        for i, c in enumerate(chunks)
    ]


REWRITE_PROMPT = """Given the conversation history and a follow-up message, rewrite the \
follow-up into a fully standalone question that makes sense with no prior context — resolve \
pronouns ("it", "that", "the timeline") and implicit references using the history. If the \
follow-up is already standalone, or isn't really a question that needs document search (e.g. \
"thanks", "hello"), return it completely unchanged. Reply with ONLY the rewritten text — no \
preamble, no quotes, no explanation.

CONVERSATION:
{conversation}

FOLLOW-UP:
{query}

STANDALONE VERSION:"""


async def _rewrite_query(query: str, history: list[ChatMessage]) -> str:
    """Fold conversation context into the retrieval query so follow-ups like
    "what about the timeline?" actually retrieve the right chunks — the raw
    follow-up alone embeds poorly since it's missing its referent. Falls
    back to the raw query on any failure; this is a retrieval-quality
    optimization, never a hard dependency."""
    if not settings.QUERY_REWRITE_ENABLED or not history:
        return query

    recent = history[-settings.QUERY_REWRITE_HISTORY_TURNS :]
    conversation = "\n".join(f"{m.role}: {m.content}" for m in recent)
    prompt = REWRITE_PROMPT.format(conversation=conversation, query=query)

    try:
        router = get_router()
        resp = await router.acompletion(
            model=MODEL_ALIAS,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            temperature=0.0,
            max_tokens=settings.QUERY_REWRITE_MAX_TOKENS,
            timeout=10,
        )
        rewritten = (resp.choices[0].message.content or "").strip().strip('"')
        return rewritten or query
    except Exception:
        logger.warning("Query rewrite failed; falling back to the raw query", exc_info=True)
        return query


async def run(
    query: str,
    history: list[ChatMessage],
    organization_id: uuid.UUID | None,
    owner_id: uuid.UUID,
    document_ids: list[str] | None = None,
) -> AsyncGenerator[PipelineEvent, None]:
    start = time.perf_counter()
    org_str = str(organization_id) if organization_id else None
    owner_str = str(owner_id)

    # 0. Fold conversation context into a standalone search query — retrieval
    # and the cache both key off this, while the LLM still sees the user's
    # original phrasing (via `query`) plus the real history messages below.
    search_query = await _rewrite_query(query, history)

    # 1. Semantic cache — bypassed entirely when the caller pinned a document
    # set. Cache entries are keyed on question + tenant only, so serving one
    # here would answer "compare A and B" with a cached answer built from a
    # different document scope. Same failure class as serving a stale answer
    # after an upload; the fix there was invalidation, and the fix here is not
    # reading from a cache that can't represent the scope.
    scoped = bool(document_ids)
    if not scoped:
        cached = await semantic_cache.lookup(search_query, org_str, owner_str)
        if cached is not None:
            yield PipelineEvent("sources", cached.sources)
            yield PipelineEvent("token", cached.answer)
            yield PipelineEvent(
                "done",
                {"cached": True, "latency_ms": int((time.perf_counter() - start) * 1000)},
            )
            return

    # 2. Retrieve
    try:
        chunks = await hybrid_search(search_query, org_str, owner_str, document_ids)
    except Exception:
        logger.warning("Document retrieval failed; continuing with no document context", exc_info=True)
        chunks = []

    # 3. Optional web fallback when documents don't cover the question
    web_results: list[dict[str, str]] = []
    if not chunks and settings.WEB_SEARCH_ENABLED:
        web_results = await web_search_service.web_search(search_query)

    sources = _build_sources(chunks)
    yield PipelineEvent("sources", [s.__dict__ for s in sources])

    context = _format_context(sources)
    if web_results:
        web_block = "\n\n".join(f"- {r['title']}: {r['content'][:400]} ({r['url']})" for r in web_results)
        context += f"\n\nWeb search results (no internal documents matched):\n{web_block}"

    messages = [{"role": "system", "content": _system_prompt_for(sources)}]
    for m in history[-settings.MAX_HISTORY_MESSAGES :]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION:\n{query}"})

    # 4. Generate, streaming tokens as they arrive
    router = get_router()
    full_text_parts: list[str] = []
    try:
        stream = await router.acompletion(
            model=MODEL_ALIAS,
            messages=messages,
            stream=True,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text_parts.append(delta)
                yield PipelineEvent("token", delta)
    except Exception as exc:
        logger.error("LLM generation failed", exc_info=True)
        error_message = (
            "I couldn't reach the language model just now. "
            "Please check that an LLM provider API key is configured and try again."
        )
        yield PipelineEvent("token", error_message)
        yield PipelineEvent("error", str(exc))
        full_text_parts = [error_message]

    full_text = "".join(full_text_parts)
    latency_ms = int((time.perf_counter() - start) * 1000)

    # Never store a scoped answer: it was produced from a caller-chosen subset
    # of documents, so a later unscoped question that matched it would inherit
    # a document scope it never asked for.
    if full_text and chunks and not scoped:
        await semantic_cache.store(search_query, full_text, [s.__dict__ for s in sources], org_str, owner_str)

    yield PipelineEvent("done", {"cached": False, "latency_ms": latency_ms})
