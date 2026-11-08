"""Deterministic chunk ids and query-embedding memoization.

Both are unit tests: no Qdrant, no ONNX models. The embedding functions are
stubbed at the batch level so only the memo layer is exercised.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import embeddings
from app.services.retrieval import chunk_point_id


class TestChunkPointId:
    def test_is_stable_across_calls(self):
        doc = uuid.uuid4()
        assert chunk_point_id(doc, 3) == chunk_point_id(doc, 3)
        assert chunk_point_id(doc, 3) == chunk_point_id(str(doc), 3)

    def test_differs_by_position_and_document(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        ids = {chunk_point_id(a, i) for i in range(50)} | {chunk_point_id(b, i) for i in range(50)}
        assert len(ids) == 100

    def test_is_a_valid_qdrant_uuid(self):
        assert uuid.UUID(chunk_point_id(uuid.uuid4(), 0)).version == 5


@pytest.fixture
def counted_embedders(monkeypatch):
    calls = {"dense": 0, "sparse": 0}

    def fake_dense(texts):
        calls["dense"] += 1
        return [[float(len(t)), 0.5] for t in texts]

    def fake_sparse(texts):
        calls["sparse"] += 1
        return [{"indices": [1, 7], "values": [0.25, float(len(t))]} for t in texts]

    monkeypatch.setattr(embeddings, "embed_dense", fake_dense)
    monkeypatch.setattr(embeddings, "embed_sparse", fake_sparse)
    embeddings._dense_one_cached.cache_clear()
    embeddings._sparse_one_cached.cache_clear()
    yield calls
    embeddings._dense_one_cached.cache_clear()
    embeddings._sparse_one_cached.cache_clear()


class TestQueryEmbeddingMemo:
    def test_repeat_query_is_embedded_once(self, counted_embedders):
        # Cache lookup, retrieval and cache store all embed the same question.
        for _ in range(3):
            assert embeddings.embed_dense_one("refund window?") == [14.0, 0.5]
            assert embeddings.embed_sparse_one("refund window?") == {
                "indices": [1, 7],
                "values": [0.25, 14.0],
            }
        assert counted_embedders == {"dense": 1, "sparse": 1}

    def test_distinct_queries_are_not_conflated(self, counted_embedders):
        assert embeddings.embed_dense_one("a") != embeddings.embed_dense_one("bb")
        assert counted_embedders["dense"] == 2

    def test_mutating_a_result_does_not_corrupt_the_cache(self, counted_embedders):
        embeddings.embed_dense_one("q").append(99.0)
        embeddings.embed_sparse_one("q")["indices"].clear()
        assert embeddings.embed_dense_one("q") == [1.0, 0.5]
        assert embeddings.embed_sparse_one("q")["indices"] == [1, 7]

    def test_size_zero_disables_memoization(self, counted_embedders, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "QUERY_EMBED_CACHE_SIZE", 0, raising=False)
        embeddings.embed_dense_one("q")
        embeddings.embed_dense_one("q")
        assert counted_embedders["dense"] == 2
