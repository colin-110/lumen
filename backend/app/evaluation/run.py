"""Retrieval evaluation harness.

Ingests the golden dataset (app/evaluation/golden_dataset.py) into an
isolated fixture namespace in the real Qdrant collection, runs every
question through four retrieval strategies using the exact same code paths
as production (app/services/retrieval.py), scores each against the known-
correct documents, and prints a comparison report.

No LLM calls — this measures retrieval only, so it costs nothing to run
and can be re-run after any change to chunking, embeddings, or the fusion/
rerank pipeline.

Run with: `python -m app.evaluation.run` from `backend/`, or `make eval-retrieval`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from app.evaluation import metrics
from app.evaluation.golden_dataset import DOCUMENTS, QUESTIONS
from app.services import retrieval
from app.services.qdrant_client import delete_owner_points, init_qdrant

logging.basicConfig(level=logging.WARNING)  # keep model-loading INFO noise out of the report
logger = logging.getLogger(__name__)

# Stable, deterministic ids so re-running the harness is idempotent and
# never collides with real tenant data (no real owner_id will ever equal
# this fixed UUID5).
_NAMESPACE = uuid.UUID("2f6a2b0e-2b0a-4e2b-9c3a-8f1e0d6a7b10")
EVAL_OWNER_ID = uuid.uuid5(_NAMESPACE, "eval-harness-owner")


@dataclass
class StrategyResult:
    name: str
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_10: float = 0.0
    avg_latency_ms: float = 0.0


def _doc_uuid(doc_key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"doc:{doc_key}")


async def _ingest_fixtures() -> None:
    init_qdrant()
    delete_owner_points(str(EVAL_OWNER_ID))
    for doc in DOCUMENTS:
        await retrieval.index_chunks(
            document_id=_doc_uuid(doc.doc_key),
            filename=doc.filename,
            owner_id=EVAL_OWNER_ID,
            organization_id=None,
            chunks=[doc.text],
        )


def _ranked_doc_ids(chunks) -> list[str]:
    """Collapse a ranked chunk list to unique document ids, keeping the
    first (best) occurrence of each — ground truth is document-level."""
    seen: list[str] = []
    for chunk in chunks:
        if chunk.document_id not in seen:
            seen.append(chunk.document_id)
    return seen


async def _score_strategy(name: str, search_fn) -> StrategyResult:
    result = StrategyResult(name=name)
    n = len(QUESTIONS)
    recall5_sum = recall10_sum = mrr_sum = ndcg_sum = 0.0
    latency_sum_ms = 0.0

    for q in QUESTIONS:
        relevant_str = {str(_doc_uuid(key)) for key in q.relevant_doc_keys}

        start = time.perf_counter()
        chunks = await search_fn(q.question, None, str(EVAL_OWNER_ID), 10)
        latency_sum_ms += (time.perf_counter() - start) * 1000

        ranked = _ranked_doc_ids(chunks)
        recall5_sum += metrics.recall_at_k(ranked, relevant_str, 5)
        recall10_sum += metrics.recall_at_k(ranked, relevant_str, 10)
        mrr_sum += metrics.reciprocal_rank(ranked, relevant_str)
        ndcg_sum += metrics.ndcg_at_k(ranked, relevant_str, 10)

    result.recall_at_5 = recall5_sum / n
    result.recall_at_10 = recall10_sum / n
    result.mrr = mrr_sum / n
    result.ndcg_at_10 = ndcg_sum / n
    result.avg_latency_ms = latency_sum_ms / n
    return result


def _print_report(results: list[StrategyResult]) -> None:
    header = f"| {'Strategy':<20} | {'Recall@5':>9} | {'Recall@10':>10} | {'MRR':>6} | {'NDCG@10':>8} | {'Avg latency':>12} |"
    sep = f"|{'-' * 22}|{'-' * 11}|{'-' * 12}|{'-' * 8}|{'-' * 10}|{'-' * 14}|"
    print("\nRetrieval strategy comparison")
    print(f"({len(QUESTIONS)} questions, {len(DOCUMENTS)} fixture documents, top-10 per strategy)\n")
    print(header)
    print(sep)
    for r in results:
        print(
            f"| {r.name:<20} | {r.recall_at_5:>8.0%} | {r.recall_at_10:>9.0%} | "
            f"{r.mrr:>6.2f} | {r.ndcg_at_10:>8.2f} | {r.avg_latency_ms:>10.0f}ms |"
        )
    print()


async def main(keep_fixtures: bool = False) -> list[StrategyResult]:
    logger.info("Ingesting %d golden documents into the eval namespace...", len(DOCUMENTS))
    await _ingest_fixtures()

    strategies = [
        ("Dense only", retrieval.dense_search),
        ("BM25 (sparse) only", retrieval.sparse_search),
        ("Hybrid (RRF)", retrieval.hybrid_search_no_rerank),
        ("Hybrid + reranker", retrieval.hybrid_search_reranked),
    ]

    results = []
    for name, fn in strategies:
        print(f"Running: {name}...")
        results.append(await _score_strategy(name, fn))

    _print_report(results)

    if not keep_fixtures:
        delete_owner_points(str(EVAL_OWNER_ID))
    else:
        print(f"Fixtures left in Qdrant under owner_id={EVAL_OWNER_ID} (--keep passed).")

    return results


if __name__ == "__main__":
    import sys

    asyncio.run(main(keep_fixtures="--keep" in sys.argv))
