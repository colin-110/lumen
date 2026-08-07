"""Generation evaluation harness.

Runs the golden dataset's questions through the real RAG pipeline (the
same retrieval + prompt + LiteLLM call as production chat, in
app/services/agent.py) and scores each answer with an LLM judge for
faithfulness, answer relevancy, and correctness against a known-good
answer — then reports an aggregate hallucination rate.

Unlike the retrieval harness, this costs real LLM tokens: two calls per
question (one generation, one judge). It therefore evaluates only the
first DEFAULT_SAMPLE_SIZE questions of the golden dataset by default,
because Gemini's free tier caps this model at 20 requests/day — a full
17-question run needs ~34 calls and cannot complete on a free key.

Run with: `python -m app.evaluation.run_generation [N]` from `backend/`,
or `make eval-generation`. Pass N to evaluate a different number of
questions (`... 17` for the full set, on a paid key).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.config import settings
from app.evaluation.fixtures import EVAL_OWNER_ID, cleanup_fixtures, ingest_fixtures
from app.evaluation.golden_dataset import DOCUMENTS, QUESTIONS
from app.evaluation.judge import judge_answer

# Private helpers imported on purpose: the harness is only meaningful if it
# grades the *actual* production prompt and context formatting. Re-declaring
# them here would let the eval silently drift from what chat really sends.
from app.services.agent import SYSTEM_PROMPT, _build_sources, _format_context
from app.services.llm_router import MODEL_ALIAS, get_router
from app.services.retrieval import hybrid_search

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    question: str
    answer: str
    faithfulness: float
    answer_relevancy: float
    answer_correctness: float
    unsupported_claims: list[str]
    latency_ms: float


async def _generate_answer(question: str, context: str) -> str:
    router = get_router()
    resp = await router.acompletion(
        model=MODEL_ALIAS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"},
        ],
        stream=False,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        timeout=30,
    )
    return (resp.choices[0].message.content or "").strip()


DEFAULT_SAMPLE_SIZE = 8  # 2 calls each = 16, just under the 20/day free-tier cap

RETRY_DELAYS_SECONDS = [5, 20, 40]  # generous — this app's litellm Router has a single
# deployment configured by default (see llm_router.py), so any single failed call opens
# a 30s cooldown on the *only* deployment and cascades into every subsequent question
# failing instantly. A batch eval job should ride that out rather than lose the whole run.


async def _run_case(question, org_str, owner_str) -> CaseResult:
    start = time.perf_counter()
    chunks = await hybrid_search(question.question, org_str, owner_str)
    sources = _build_sources(chunks)
    context = _format_context(chunks)

    answer = await _generate_answer(question.question, context)
    verdict = await judge_answer(question.question, question.expected_answer, context, answer)
    latency_ms = (time.perf_counter() - start) * 1000

    return CaseResult(
        question=question.question,
        answer=answer,
        faithfulness=verdict.faithfulness,
        answer_relevancy=verdict.answer_relevancy,
        answer_correctness=verdict.answer_correctness,
        unsupported_claims=verdict.unsupported_claims,
        latency_ms=latency_ms,
    )


def _print_report(results: list[CaseResult]) -> None:
    n = len(results)
    avg_faithfulness = sum(r.faithfulness for r in results) / n
    avg_relevancy = sum(r.answer_relevancy for r in results) / n
    avg_correctness = sum(r.answer_correctness for r in results) / n
    avg_latency = sum(r.latency_ms for r in results) / n
    hallucinated = [r for r in results if r.faithfulness < 1.0]
    hallucination_rate = len(hallucinated) / n

    print("\nGeneration evaluation")
    print(f"({n} questions, judged by {MODEL_ALIAS} via LiteLLM router)\n")
    print(f"Faithfulness:        {avg_faithfulness:.2f}")
    print(f"Answer relevancy:    {avg_relevancy:.2f}")
    print(f"Answer correctness:  {avg_correctness:.2f}")
    print(f"Hallucination rate:  {hallucination_rate:.1%}  ({len(hallucinated)}/{n} answers had an unsupported claim)")
    print(f"Avg latency:         {avg_latency:.0f}ms\n")

    if hallucinated:
        print("Answers with unsupported claims:")
        for r in hallucinated:
            claims = "; ".join(r.unsupported_claims) or "(judge flagged it but listed no specific claim)"
            print(f"  - [{r.faithfulness:.2f}] \"{r.question}\" -> {claims}")
        print()


async def main(keep_fixtures: bool = False, sample_size: int = DEFAULT_SAMPLE_SIZE) -> list[CaseResult]:
    logger.info("Ingesting %d golden documents into the eval namespace...", len(DOCUMENTS))
    await ingest_fixtures()

    questions = QUESTIONS[:sample_size]
    if len(questions) < len(QUESTIONS):
        print(
            f"Evaluating {len(questions)} of {len(QUESTIONS)} golden questions "
            f"(~{len(questions) * 2} LLM calls). Pass a larger N to widen the sample.\n"
        )

    org_str = None
    owner_str = str(EVAL_OWNER_ID)

    results = []
    skipped = 0
    for i, q in enumerate(questions, start=1):
        print(f"[{i}/{len(questions)}] {q.question}")
        last_exc: Exception | None = None
        for delay in [0, *RETRY_DELAYS_SECONDS]:
            if delay:
                logger.warning("Retrying %r in %ds after: %s", q.question, delay, last_exc)
                await asyncio.sleep(delay)
            try:
                results.append(await _run_case(q, org_str, owner_str))
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - any provider failure is retryable here
                last_exc = exc
        if last_exc is not None:
            # Every retry exhausted — a single provider outage shouldn't discard
            # every question that already succeeded; skip and keep going.
            skipped += 1
            logger.warning("Skipping %r after %d attempts: %s", q.question, len(RETRY_DELAYS_SECONDS) + 1, last_exc)

    if not results:
        print("\nEvery question failed — no report to generate. Check LLM provider connectivity.")
    else:
        if skipped:
            print(f"\n({skipped}/{len(questions)} questions skipped after a provider error)")
        _print_report(results)

    if not keep_fixtures:
        cleanup_fixtures()
    else:
        print(f"Fixtures left in Qdrant under owner_id={EVAL_OWNER_ID} (--keep passed).")

    return results


if __name__ == "__main__":
    import sys

    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    n = int(positional[0]) if positional else DEFAULT_SAMPLE_SIZE
    asyncio.run(main(keep_fixtures="--keep" in sys.argv, sample_size=n))
