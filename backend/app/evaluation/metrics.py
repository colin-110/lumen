"""Standard IR ranking metrics, computed against binary (relevant/not)
document-level relevance judgments from the golden dataset.

Each function takes a ranked list of retrieved document ids (best first,
duplicates already collapsed to first occurrence — see `run.py`) and the
set of ids that are actually correct for that question.
"""

from __future__ import annotations

import math


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = len(set(retrieved[:k]) & relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    hits = len(set(retrieved[:k]) & relevant)
    return hits / k


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Binary-relevance NDCG@k: gain is 1 for a relevant doc at that rank, 0
    otherwise, discounted by log2(rank + 1)."""
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, doc_id in enumerate(retrieved[:k], start=1)
        if doc_id in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
