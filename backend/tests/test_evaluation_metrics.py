from app.evaluation.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_counts_hits_within_cutoff():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"c", "z"}
    assert recall_at_k(retrieved, relevant, k=3) == 0.5  # only "c" is within top-3
    assert recall_at_k(retrieved, relevant, k=5) == 0.5  # "z" never appears at all


def test_recall_at_k_with_no_relevant_docs_is_zero():
    assert recall_at_k(["a", "b"], set(), k=5) == 0.0


def test_precision_at_k_divides_by_k_not_by_hits():
    retrieved = ["a", "b", "c"]
    relevant = {"a", "c"}
    assert precision_at_k(retrieved, relevant, k=3) == 2 / 3


def test_reciprocal_rank_uses_first_relevant_hit():
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == 1 / 3
    assert reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0
    assert reciprocal_rank(["a", "b", "c"], {"z"}) == 0.0


def test_ndcg_at_k_is_one_for_perfectly_ranked_relevant_docs():
    retrieved = ["a", "b", "c"]
    relevant = {"a", "b"}
    assert ndcg_at_k(retrieved, relevant, k=3) == 1.0


def test_ndcg_at_k_penalizes_relevant_docs_ranked_lower():
    perfect = ndcg_at_k(["a", "b", "c"], {"a"}, k=3)
    worse = ndcg_at_k(["c", "b", "a"], {"a"}, k=3)
    assert worse < perfect


def test_ndcg_at_k_with_no_relevant_docs_is_zero():
    assert ndcg_at_k(["a", "b"], set(), k=5) == 0.0
