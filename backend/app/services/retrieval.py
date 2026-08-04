"""Hybrid retrieval: dense + sparse (BM25) fused with RRF, then cross-encoder
reranked. This is the "accuracy" half of the speed/accuracy ask — dense
vectors catch semantic matches, BM25 sparse vectors catch exact keyword/
identifier matches dense embeddings blur together (part numbers, error
codes, acronyms), and the reranker fixes the ordering RRF alone gets wrong.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from qdrant_client.http import models

from app.core.config import settings
from app.services import embeddings
from app.services.qdrant_client import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    client as qdrant,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    text: str
    score: float


def _tenant_filter(organization_id: str | None, owner_id: str) -> models.Filter:
    # Documents are visible within an organization; users without an org
    # only see their own uploads.
    if organization_id:
        return models.Filter(
            must=[models.FieldCondition(key="organization_id", match=models.MatchValue(value=organization_id))]
        )
    return models.Filter(
        must=[models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id))]
    )


def _search_sync(query: str, organization_id: str | None, owner_id: str) -> list[RetrievedChunk]:
    dense_vec = embeddings.embed_dense_one(query)
    sparse = embeddings.embed_sparse_one(query)
    query_filter = _tenant_filter(organization_id, owner_id)
    candidates = settings.RETRIEVE_CANDIDATES

    result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=dense_vec,
                using=DENSE_VECTOR_NAME,
                limit=candidates,
                filter=query_filter,
            ),
            models.Prefetch(
                query=models.SparseVector(indices=sparse["indices"], values=sparse["values"]),
                using=SPARSE_VECTOR_NAME,
                limit=candidates,
                filter=query_filter,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=candidates,
        with_payload=True,
    )

    points = result.points
    if not points:
        return []

    texts = [p.payload.get("text", "") for p in points]
    rerank_scores = embeddings.rerank(query, texts)

    scored = [
        RetrievedChunk(
            chunk_id=str(p.id),
            document_id=p.payload.get("document_id", ""),
            filename=p.payload.get("filename", "unknown"),
            text=p.payload.get("text", ""),
            score=float(score),
        )
        for p, score in zip(points, rerank_scores)
    ]
    scored.sort(key=lambda c: c.score, reverse=True)
    top = [c for c in scored if c.score >= settings.MIN_RERANK_SCORE][: settings.RERANK_TOP_K]
    # If the score floor filtered out everything, fall back to the best few
    # candidates rather than returning nothing — a weak match still beats no
    # context for the agent to reason from.
    return top or scored[: min(3, len(scored))]


async def hybrid_search(query: str, organization_id: str | None, owner_id: str) -> list[RetrievedChunk]:
    return await asyncio.to_thread(_search_sync, query, organization_id, owner_id)


def _upsert_sync(
    document_id: uuid.UUID,
    filename: str,
    owner_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    chunks: list[str],
) -> int:
    if not chunks:
        return 0
    dense_vecs = embeddings.embed_dense(chunks)
    sparse_vecs = embeddings.embed_sparse(chunks)

    points = []
    for text, dense, sparse in zip(chunks, dense_vecs, sparse_vecs):
        points.append(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    DENSE_VECTOR_NAME: dense,
                    SPARSE_VECTOR_NAME: models.SparseVector(indices=sparse["indices"], values=sparse["values"]),
                },
                payload={
                    "document_id": str(document_id),
                    "filename": filename,
                    "owner_id": str(owner_id),
                    "organization_id": str(organization_id) if organization_id else None,
                    "text": text,
                },
            )
        )

    batch_size = 64
    for i in range(0, len(points), batch_size):
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points[i : i + batch_size])
    return len(points)


async def index_chunks(
    document_id: uuid.UUID,
    filename: str,
    owner_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    chunks: list[str],
) -> int:
    return await asyncio.to_thread(_upsert_sync, document_id, filename, owner_id, organization_id, chunks)
