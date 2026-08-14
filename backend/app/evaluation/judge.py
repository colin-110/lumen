"""LLM-as-judge scoring for generated answers, via the same LiteLLM router
production chat uses — no new dependency, no separate provider config.

Each question costs one judge call (faithfulness, answer relevancy, and
answer correctness are scored together in a single structured-output
request rather than three separate calls) on top of the one generation
call already needed to produce the answer being judged.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.services.llm_router import MODEL_ALIAS, get_router

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """You are grading a RAG system's answer. Be strict and literal — do not give \
credit for plausible-sounding claims that aren't actually stated in the CONTEXT.

CONTEXT (what the system was allowed to ground its answer in):
{context}

QUESTION:
{question}

EXPECTED ANSWER (ground truth, for correctness only — the system did not see this):
{expected_answer}

SYSTEM'S ANSWER:
{answer}

Score three things, each from 0.0 to 1.0:
- faithfulness: what fraction of the factual claims in the system's answer are directly \
supported by CONTEXT? A claim not present in CONTEXT (even if true) counts against this, unless \
the answer explicitly labels it as general knowledge rather than document-grounded.
- answer_relevancy: does the answer actually address what QUESTION asked, regardless of whether \
it's correct?
- answer_correctness: does the answer convey the same information as EXPECTED ANSWER?

Also list any claims in the system's answer that are NOT supported by CONTEXT.

Reply with ONLY a JSON object, no markdown fences, no other text:
{{"faithfulness": <float>, "answer_relevancy": <float>, "answer_correctness": <float>, \
"unsupported_claims": [<string>, ...]}}"""


@dataclass
class JudgeResult:
    faithfulness: float
    answer_relevancy: float
    answer_correctness: float
    unsupported_claims: list[str]


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _clamp01(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


async def judge_answer(
    question: str, expected_answer: str, context: str, answer: str
) -> JudgeResult:
    prompt = JUDGE_PROMPT.format(
        context=context or "(no context was retrieved)",
        question=question,
        expected_answer=expected_answer,
        answer=answer,
    )
    router = get_router()
    resp = await router.acompletion(
        model=MODEL_ALIAS,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        temperature=0.0,
        # Generous headroom: some models emit reasoning text before the JSON
        # despite being told not to, and 600 was tight enough that the JSON
        # itself got cut off mid-object rather than just preceded by prose —
        # that's a truncated-response parse failure, not a real judge
        # verdict, and must not be scored as 0 the way a real refusal would.
        max_tokens=2048,
        timeout=30,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Judge returned unparseable output, scoring as 0: %r", raw[:200])
        return JudgeResult(0.0, 0.0, 0.0, ["<judge output was not valid JSON>"])

    claims = parsed.get("unsupported_claims") or []
    if not isinstance(claims, list):
        claims = [str(claims)]

    return JudgeResult(
        faithfulness=_clamp01(parsed.get("faithfulness")),
        answer_relevancy=_clamp01(parsed.get("answer_relevancy")),
        answer_correctness=_clamp01(parsed.get("answer_correctness")),
        unsupported_claims=[str(c) for c in claims],
    )
