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


def _tenant_filter(organization_id: str | None, owner_id: str) -> list[models.FieldCondition]:
    now = time.time()
    conditions = [models.FieldCondition(key="expires_at", range=models.Range(gt=now))]
    if organization_id:
        conditions.append(
            models.FieldCondition(key="organization_id", match=models.MatchValue(value=organization_id))
        )
    else:
        conditions.append(models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id)))
    return conditions


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
    query: str, answer: str, sources: list[dict[str, Any]], organization_id: str | None, owner_id: str
) -> None:
    vec = embeddings.embed_dense_one(query)
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
    query: str, answer: str, sources: list[dict[str, Any]], organization_id: str | None, owner_id: str
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
            filter=models.Filter(must=_tenant_filter(organization_id, owner_id)[1:])
        ),
    )


async def invalidate(organization_id: str | None, owner_id: str) -> None:
    """Bust every cached answer for this tenant. Call whenever the document set
    changes (ingestion completes, a document is deleted) so a near-duplicate
    question can't serve a stale answer/citations from before the change —
    the cache has no other way to know the underlying document set moved."""
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        await asyncio.to_thread(_invalidate_sync, organization_id, owner_id)
    except Exception:
        logger.warning("Semantic cache invalidation failed", exc_info=True)
