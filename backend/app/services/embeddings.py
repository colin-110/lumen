"""Embedding & reranking models, backed by fastembed's ONNX runtimes.

Deliberately not `sentence-transformers`/`torch`: fastembed ships quantized
ONNX graphs that load in ~1-2s and run fast on CPU, which matters a lot here
because the API process, the Celery worker, *and* every autoscaled replica
each load a copy. Dense + sparse (BM25) + cross-encoder together are still a
much smaller and faster footprint than a single torch install.

Everything in this module is synchronous CPU work under the hood; callers
run it via `asyncio.to_thread` so it never blocks the event loop.
"""

from __future__ import annotations

import logging
import threading

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_dense: TextEmbedding | None = None
_sparse: SparseTextEmbedding | None = None
_reranker: TextCrossEncoder | None = None


def _threads() -> int | None:
    return settings.ONNX_THREADS or None


def get_dense_model() -> TextEmbedding:
    global _dense
    if _dense is None:
        with _lock:
            if _dense is None:
                logger.info("Loading dense embedding model %s", settings.DENSE_MODEL)
                _dense = TextEmbedding(model_name=settings.DENSE_MODEL, threads=_threads())
    return _dense


def get_sparse_model() -> SparseTextEmbedding:
    global _sparse
    if _sparse is None:
        with _lock:
            if _sparse is None:
                logger.info("Loading sparse embedding model %s", settings.SPARSE_MODEL)
                _sparse = SparseTextEmbedding(model_name=settings.SPARSE_MODEL, threads=_threads())
    return _sparse


def get_reranker() -> TextCrossEncoder:
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:
                logger.info("Loading cross-encoder reranker %s", settings.RERANK_MODEL)
                _reranker = TextCrossEncoder(model_name=settings.RERANK_MODEL, threads=_threads())
    return _reranker


def warm_up() -> None:
    """Force all three models to load. Call once at process startup so the
    first real request isn't the one paying the ~1-2s model-load cost."""
    get_dense_model()
    get_sparse_model()
    get_reranker()


def embed_dense(texts: list[str]) -> list[list[float]]:
    return [
        vec.tolist() for vec in get_dense_model().embed(texts, batch_size=settings.EMBED_BATCH_SIZE)
    ]


def embed_dense_one(text: str) -> list[float]:
    return embed_dense([text])[0]


def embed_sparse(texts: list[str]) -> list[dict]:
    results = []
    for vec in get_sparse_model().embed(texts, batch_size=settings.EMBED_BATCH_SIZE):
        results.append({"indices": vec.indices.tolist(), "values": vec.values.tolist()})
    return results


def embed_sparse_one(text: str) -> dict:
    return embed_sparse([text])[0]


def rerank(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    return list(get_reranker().rerank(query, documents))
