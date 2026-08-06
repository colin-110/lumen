"""Qdrant collection bootstrap.

Two collections:
  * `settings.QDRANT_COLLECTION`   — document chunks, hybrid dense+sparse
  * `settings.QDRANT_CACHE_COLLECTION` — semantic cache of (question -> answer)

Both are created idempotently on startup with payload indexes for the
filters we actually query on, so tenant-scoped search stays fast as the
collection grows instead of falling back to a full scan.
"""

from __future__ import annotations

import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings

logger = logging.getLogger(__name__)

client = QdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY,
    timeout=settings.QDRANT_TIMEOUT,
)

COLLECTION_NAME = settings.QDRANT_COLLECTION
CACHE_COLLECTION_NAME = settings.QDRANT_CACHE_COLLECTION

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def _ensure_document_collection() -> None:
    if client.collection_exists(COLLECTION_NAME):
        return
    logger.info("Creating Qdrant collection %s", COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            DENSE_VECTOR_NAME: models.VectorParams(
                size=settings.DENSE_DIM,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
        },
        hnsw_config=models.HnswConfigDiff(m=32, ef_construct=200, on_disk=False),
        optimizers_config=models.OptimizersConfigDiff(default_segment_number=2),
    )
    for field, schema in (
        ("organization_id", models.PayloadSchemaType.KEYWORD),
        ("owner_id", models.PayloadSchemaType.KEYWORD),
        ("document_id", models.PayloadSchemaType.KEYWORD),
    ):
        client.create_payload_index(COLLECTION_NAME, field_name=field, field_schema=schema)


def _ensure_cache_collection() -> None:
    if client.collection_exists(CACHE_COLLECTION_NAME):
        return
    logger.info("Creating Qdrant collection %s", CACHE_COLLECTION_NAME)
    client.create_collection(
        collection_name=CACHE_COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=settings.DENSE_DIM,
            distance=models.Distance.COSINE,
        ),
    )
    client.create_payload_index(
        CACHE_COLLECTION_NAME, field_name="organization_id", field_schema=models.PayloadSchemaType.KEYWORD
    )
    client.create_payload_index(
        CACHE_COLLECTION_NAME, field_name="expires_at", field_schema=models.PayloadSchemaType.FLOAT
    )


def init_qdrant() -> None:
    _ensure_document_collection()
    _ensure_cache_collection()


def delete_document_points(document_id: str) -> None:
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
            )
        ),
    )


def delete_owner_points(owner_id: str) -> None:
    """Wipe every chunk indexed under a given owner_id. Used by the retrieval
    eval harness to clear its isolated fixture namespace between runs — not
    called from any user-facing path."""
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id))])
        ),
    )
