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
)
from app.services.qdrant_client import (
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


def _tenant_filter(
    organization_id: str | None, owner_id: str, document_ids: list[str] | None = None
) -> models.Filter:
    # Documents are visible within an organization; users without an org
    # only see their own uploads.
    if organization_id:
        must = [
            models.FieldCondition(
                key="organization_id", match=models.MatchValue(value=organization_id)
            )
        ]
    else:
        must = [models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id))]
    if document_ids:
        # Narrow to an explicit document set on top of — never instead of —
        # the tenant scope, so a caller-supplied id can't reach another org's
        # chunks.
        must.append(
            models.FieldCondition(key="document_id", match=models.MatchAny(any=list(document_ids)))
        )
    return models.Filter(must=must)


def allocate_fairly(chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    """Fill a context budget round-robin across documents instead of by pure
    global rank.

    Straight top-k lets one long document monopolise the budget: a 7-chunk
    contract measured here took 3 of 6 slots, and with a couple more chunks it
    would crowd the invoice out entirely — at which point a "does the invoice
    match the contract?" question is unanswerable no matter how good the model
    is, because half the comparison never reaches the prompt.

    Passes take the next-best remaining chunk from each document in turn, so
    every document contributes its best chunk before any document contributes
    a second. Relative order within a document is preserved, and the input is
    assumed to be sorted best-first.
    """
    if limit <= 0:
        return []

    by_doc: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk)

    # Document order follows each document's best-ranked chunk, so the most
    # relevant document still leads the context.
    doc_order = list(by_doc.keys())

    selected: list[RetrievedChunk] = []
    depth = 0
    while len(selected) < limit:
        progressed = False
        for doc_id in doc_order:
            queue = by_doc[doc_id]
            if depth < len(queue):
                selected.append(queue[depth])
                progressed = True
                if len(selected) == limit:
                    break
        if not progressed:
            break  # every document exhausted
        depth += 1
    return selected


def _points_to_chunks(points) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=str(p.id),
            document_id=p.payload.get("document_id", ""),
            filename=p.payload.get("filename", "unknown"),
            text=p.payload.get("text", ""),
            score=float(p.score),
        )
        for p in points
    ]


def _hybrid_candidates_sync(
    query: str,
    organization_id: str | None,
    owner_id: str,
    candidates: int,
    document_ids: list[str] | None = None,
) -> tuple[list, list[str]]:
    """Shared prefetch+RRF step behind both `hybrid_search` (reranked, used in
    production) and `hybrid_search_no_rerank` (used by the retrieval eval
    harness to isolate what RRF fusion alone contributes vs. the reranker)."""
    dense_vec = embeddings.embed_dense_one(query)
    sparse = embeddings.embed_sparse_one(query)
    query_filter = _tenant_filter(organization_id, owner_id, document_ids)

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
    texts = [p.payload.get("text", "") for p in points]
    return points, texts


def _search_sync(
    query: str,
    organization_id: str | None,
    owner_id: str,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    points, texts = _hybrid_candidates_sync(
        query, organization_id, owner_id, settings.RETRIEVE_CANDIDATES, document_ids
    )
    if not points:
        return []

    rerank_scores = embeddings.rerank(query, texts)
    # strict=True: one score per candidate is an invariant of the reranker.
    # Silently zipping to the shorter list would drop retrieved chunks out of
    # the context with no error anywhere — the answer would just quietly be
    # built from less evidence, which is the hardest kind of bug to notice.
    scored = [
        RetrievedChunk(
            chunk_id=str(p.id),
            document_id=p.payload.get("document_id", ""),
            filename=p.payload.get("filename", "unknown"),
            text=p.payload.get("text", ""),
            score=float(score),
        )
        for p, score in zip(points, rerank_scores, strict=True)
    ]
    scored.sort(key=lambda c: c.score, reverse=True)

    if document_ids:
        # Explicit multi-document scope: the user named these documents, so
        # every one of them should get a voice in the context rather than
        # letting the longest crowd the others out. The floor is intentionally
        # not applied here — excluding a document the user explicitly asked
        # about would silently make the comparison unanswerable.
        return allocate_fairly(scored, settings.RERANK_TOP_K)

    return select_within_floor(scored)


def select_within_floor(scored: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Apply the rerank score floor without starving the context.

    The cross-encoder scores anything that isn't a direct answer steeply
    negative — a chunk that is topically relevant but doesn't answer the
    question lands near -10, well under the floor. On a narrow question that's
    exactly what you want. On a broad one ("summarise everything", "what do
    these documents have in common") the floor alone collapsed the context to
    the single best chunk, so the model could only ever discuss one document
    and it read as a retrieval failure.

    The floor therefore only *trims*: it never takes the context below
    MIN_CONTEXT_CHUNKS. Below that we fall back to rank order, because a
    weakly-scored chunk still beats nothing to reason from, and the system
    prompt already tells the model to say when the context doesn't cover
    something.

    Split out from `_search_sync` so it can be tested without a live Qdrant.
    """
    above_floor = [c for c in scored if c.score >= settings.MIN_RERANK_SCORE]
    if len(above_floor) < settings.MIN_CONTEXT_CHUNKS:
        return scored[: min(settings.MIN_CONTEXT_CHUNKS, len(scored))]
    return above_floor[: settings.RERANK_TOP_K]


async def hybrid_search(
    query: str,
    organization_id: str | None,
    owner_id: str,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Production retrieval. Passing `document_ids` scopes the search to those
    documents and splits the context budget fairly between them — see
    `allocate_fairly`. Without it, behaviour is unchanged: global top-k above
    the rerank score floor."""
    return await asyncio.to_thread(_search_sync, query, organization_id, owner_id, document_ids)


# --- strategy variants below, used only by the retrieval eval harness
# (app/evaluation/) to benchmark what each stage of the pipeline actually
# contributes. Production chat always uses `hybrid_search` above.


def _dense_only_sync(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    dense_vec = embeddings.embed_dense_one(query)
    result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=dense_vec,
        using=DENSE_VECTOR_NAME,
        query_filter=_tenant_filter(organization_id, owner_id, document_ids),
        limit=limit,
        with_payload=True,
    )
    return _points_to_chunks(result.points)


async def dense_search(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int = 10,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    return await asyncio.to_thread(
        _dense_only_sync, query, organization_id, owner_id, limit, document_ids
    )


def _sparse_only_sync(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    sparse = embeddings.embed_sparse_one(query)
    result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=models.SparseVector(indices=sparse["indices"], values=sparse["values"]),
        using=SPARSE_VECTOR_NAME,
        query_filter=_tenant_filter(organization_id, owner_id, document_ids),
        limit=limit,
        with_payload=True,
    )
    return _points_to_chunks(result.points)


async def sparse_search(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int = 10,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    return await asyncio.to_thread(
        _sparse_only_sync, query, organization_id, owner_id, limit, document_ids
    )


def _hybrid_no_rerank_sync(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    points, _texts = _hybrid_candidates_sync(query, organization_id, owner_id, limit, document_ids)
    return _points_to_chunks(points)


async def hybrid_search_no_rerank(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int = 10,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    return await asyncio.to_thread(
        _hybrid_no_rerank_sync, query, organization_id, owner_id, limit, document_ids
    )


async def hybrid_search_reranked(
    query: str,
    organization_id: str | None,
    owner_id: str,
    limit: int = 10,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Same pipeline as `hybrid_search`, but returns the top `limit` reranked
    results unfiltered by MIN_RERANK_SCORE/RERANK_TOP_K — the eval harness
    needs a fixed-size ranked list per strategy to compute Recall@k/NDCG@k
    consistently; production's score-floor behavior stays only in
    `hybrid_search`/`_search_sync`."""

    def _sync() -> list[RetrievedChunk]:
        points, texts = _hybrid_candidates_sync(
            query, organization_id, owner_id, settings.RETRIEVE_CANDIDATES, document_ids
        )
        if not points:
            return []
        rerank_scores = embeddings.rerank(query, texts)
        scored = _points_to_chunks(points)
        for chunk, score in zip(scored, rerank_scores, strict=True):
            chunk.score = float(score)
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:limit]

    return await asyncio.to_thread(_sync)


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
    # strict=True for the same reason as the rerank zip above: a length
    # mismatch here would mean chunks were never indexed, so the document
    # would look ingested while part of it was silently missing from search.
    for text, dense, sparse in zip(chunks, dense_vecs, sparse_vecs, strict=True):
        points.append(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    DENSE_VECTOR_NAME: dense,
                    SPARSE_VECTOR_NAME: models.SparseVector(
                        indices=sparse["indices"], values=sparse["values"]
                    ),
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
    return await asyncio.to_thread(
        _upsert_sync, document_id, filename, owner_id, organization_id, chunks
    )
