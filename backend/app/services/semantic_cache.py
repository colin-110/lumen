"""Semantic response cache.

Rather than caching on exact prompt text (which almost never repeats
verbatim), we embed the question and do a cosine-similarity lookup against
previously-answered questions scoped to the same tenant. A near-duplicate
question ("what's our refund window?" vs "how long do customers have to
request a refund?") hits the cache instead of paying for another LLM round
trip and retrieval pass — this is what gets sub-100ms replies
on repeat/rephrased questions at real usage volume.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client.http import models

from app.core.config import settings
from app.services import embeddings
from app.services.qdrant_client import CACHE_COLLECTION_NAME
from app.services.qdrant_client import client as qdrant

logger = logging.getLogger(__name__)


@dataclass
class CacheHit:
    answer: str
    sources: list[dict[str, Any]]


def _scope_condition(organization_id: str | None, owner_id: str) -> models.FieldCondition:
    if organization_id:
        return models.FieldCondition(
            key="organization_id", match=models.MatchValue(value=organization_id)
        )
    return models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id))


def _tenant_filter(organization_id: str | None, owner_id: str) -> list[models.FieldCondition]:
    now = time.time()
    return [
        models.FieldCondition(key="expires_at", range=models.Range(gt=now)),
        _scope_condition(organization_id, owner_id),
    ]


def _lookup_sync(query: str, organization_id: str | None, owner_id: str) -> CacheHit | None:
    vec = embeddings.embed_dense_one(query)
    # `query_points`, not the removed `search`. qdrant-client dropped `search`
    # in favour of the unified query API; the call raised AttributeError on
    # every lookup, `lookup()` caught it and logged a warning, and the cache
    # silently reported a miss forever. Nothing failed loudly, so the feature
    # looked present while every question paid full retrieval + generation.
    # Found by a load test, not by reading the code.
    result = qdrant.query_points(
        collection_name=CACHE_COLLECTION_NAME,
        query=vec,
        query_filter=models.Filter(must=_tenant_filter(organization_id, owner_id)),
        limit=1,
        score_threshold=settings.SEMANTIC_CACHE_THRESHOLD,
        with_payload=True,
    )
    hits = result.points
    if not hits:
        return None
    payload = hits[0].payload or {}
    return CacheHit(answer=payload.get("answer", ""), sources=payload.get("sources", []))


def _store_sync(
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    organization_id: str | None,
    owner_id: str,
) -> None:
    vec = embeddings.embed_dense_one(query)
    # Recorded so a single document's deletion can invalidate exactly the
    # answers that cited it, instead of every answer the tenant ever received.
    document_ids = sorted({s["document_id"] for s in sources if s.get("document_id")})
    qdrant.upsert(
        collection_name=CACHE_COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "question": query,
                    "answer": answer,
                    "sources": sources,
                    "document_ids": document_ids,
                    "organization_id": organization_id,
                    "owner_id": owner_id,
                    "expires_at": time.time() + settings.SEMANTIC_CACHE_TTL_SECONDS,
                },
            )
        ],
    )


async def lookup(query: str, organization_id: str | None, owner_id: str) -> CacheHit | None:
    if not settings.SEMANTIC_CACHE_ENABLED:
        return None
    try:
        return await asyncio.to_thread(_lookup_sync, query, organization_id, owner_id)
    except Exception:
        logger.warning("Semantic cache lookup failed; continuing without cache", exc_info=True)
        return None


async def store(
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    organization_id: str | None,
    owner_id: str,
) -> None:
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        await asyncio.to_thread(_store_sync, query, answer, sources, organization_id, owner_id)
    except Exception:
        logger.warning("Semantic cache write failed", exc_info=True)


def _invalidate_sync(organization_id: str | None, owner_id: str) -> None:
    qdrant.delete(
        collection_name=CACHE_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[_scope_condition(organization_id, owner_id)])
        ),
    )


async def invalidate(organization_id: str | None, owner_id: str) -> None:
    """Bust every cached answer for this tenant.

    Used when a document is *added*. It is deliberately the blunt instrument:
    a new document can change the answer to a question whose cached entry
    cites entirely different documents (or none at all), and there is no way
    to identify those entries without re-running retrieval for every one of
    them. Over-invalidating costs cache hits; under-invalidating serves
    answers that are now wrong.

    Deletion is the precise case — see `invalidate_for_document`.
    """
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        await asyncio.to_thread(_invalidate_sync, organization_id, owner_id)
    except Exception:
        logger.warning("Semantic cache invalidation failed", exc_info=True)


def _invalidate_for_document_sync(
    organization_id: str | None, owner_id: str, document_id: str
) -> None:
    qdrant.delete(
        collection_name=CACHE_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    _scope_condition(organization_id, owner_id),
                    models.FieldCondition(
                        key="document_ids", match=models.MatchValue(value=document_id)
                    ),
                ]
            )
        ),
    )


async def invalidate_for_document(
    organization_id: str | None, owner_id: str, document_id: str
) -> None:
    """Drop only the cached answers that cited a now-deleted document.

    Removing a document cannot change an answer that never referenced it, so
    wiping the tenant's whole cache here just throws away valid work. In an
    organization that uploads and deletes regularly, that blanket wipe kept
    the cache empty almost all the time — the feature was present but
    unreachable.
    """
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        await asyncio.to_thread(
            _invalidate_for_document_sync, organization_id, owner_id, document_id
        )
    except Exception:
        logger.warning("Semantic cache invalidation failed", exc_info=True)


def _evict_expired_sync() -> None:
    qdrant.delete(
        collection_name=CACHE_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="expires_at", range=models.Range(lte=time.time()))]
            )
        ),
    )


async def evict_expired() -> None:
    """Delete entries past their TTL.

    `expires_at` was only ever used as a *read* filter, so expired points were
    skipped by lookups but never removed: every question the system had ever
    answered stayed in Qdrant forever as a vector plus its full answer text.
    The collection grew without bound and search slowed with it. Run
    periodically from the app lifespan.
    """
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        await asyncio.to_thread(_evict_expired_sync)
    except Exception:
        logger.warning("Semantic cache eviction sweep failed", exc_info=True)
