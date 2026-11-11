"""Production retrieval uses late interaction only when the collection has it."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.services import qdrant_client as qdrant_store
from app.services import retrieval


def _point(i: int, doc: str = "d1"):
    return SimpleNamespace(
        id=f"c{i}",
        score=10.0 - i,
        payload={"document_id": doc, "filename": f"{doc}.txt", "text": f"t{i}"},
    )


def test_colbert_path_is_used_when_available(monkeypatch):
    monkeypatch.setattr(qdrant_store, "colbert_available", True)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(
        retrieval, "_colbert_ranked_sync", lambda *a, **k: [_point(i) for i in range(10)]
    )
    monkeypatch.setattr(
        retrieval,
        "_hybrid_candidates_sync",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cross-encoder path used")),
    )
    out = retrieval._search_sync("q", None, "owner")
    assert [c.chunk_id for c in out] == [f"c{i}" for i in range(settings.RERANK_TOP_K)]


def test_falls_back_to_the_cross_encoder_without_colbert_vectors(monkeypatch):
    monkeypatch.setattr(qdrant_store, "colbert_available", False)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(
        retrieval,
        "_colbert_ranked_sync",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("colbert used")),
    )
    points = [_point(i) for i in range(3)]
    monkeypatch.setattr(
        retrieval, "_hybrid_candidates_sync", lambda *a, **k: (points, ["t0", "t1", "t2"])
    )
    monkeypatch.setattr(retrieval.embeddings, "rerank", lambda q, docs: [1.0, 3.0, 2.0])
    out = retrieval._search_sync("q", None, "owner")
    assert [c.chunk_id for c in out][:1] == ["c1"]  # reordered by the cross-encoder scores


def test_scoped_colbert_search_shares_the_budget_across_documents(monkeypatch):
    monkeypatch.setattr(qdrant_store, "colbert_available", True)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    pts = [_point(i, "a") for i in range(8)] + [_point(i + 8, "b") for i in range(2)]
    monkeypatch.setattr(retrieval, "_colbert_ranked_sync", lambda *a, **k: pts)
    out = retrieval._search_sync("q", None, "owner", document_ids=["a", "b"])
    assert {c.document_id for c in out} == {"a", "b"}
