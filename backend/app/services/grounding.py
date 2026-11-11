"""Check every figure in an answer against the source it cites.

A model that misreads "4,200" as "4,500", or invents a due date, produces an
answer that reads exactly as confidently as a correct one. For contracts and
invoices that is the failure that matters most, and it is cheap to catch
mechanically: each sentence cites its sources, so every number in the
sentence should appear in one of them.

This is string matching, not another model call: it adds no latency worth
measuring and costs nothing. It checks figures only (amounts, percentages,
counts, dates' numeric parts), which is where a wrong answer does damage.
A value the model derived rather than quoted (a due date computed from net
30) is reported as not found in the source, which is accurate: the reader
should check derived figures.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
# Reference codes ("INV-2026-0412", "MSA-2026-017") are names, not figures.
_IDENTIFIER = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z0-9]+)+\b")
# A list marker ("1." / "2)") at the start of a line is structure, not a claim.
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_(\"'])")


def _normalise(token: str) -> str | None:
    pct = token.endswith("%")
    raw = token.rstrip("%").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text + ("%" if pct else "")


def _figures(text: str) -> set[str]:
    found = set()
    for match in _NUMBER.finditer(_IDENTIFIER.sub(" ", text)):
        norm = _normalise(match.group())
        if norm is not None:
            found.add(norm)
    return found


@dataclass
class Claim:
    text: str
    citations: list[int]
    figures: list[str]
    missing: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.citations:
            return "uncited"
        return "unverified" if self.missing else "verified"


def _claims(answer: str) -> list[tuple[str, list[int]]]:
    out = []
    for line in answer.splitlines():
        line = _LIST_MARKER.sub("", line).strip()
        if not line:
            continue
        for sentence in _SENTENCE_END.split(line):
            cites = [int(n) for group in _CITATION.findall(sentence) for n in group.split(",")]
            out.append((sentence.strip(), cites))
    return out


def verify_figures(answer: str, sources: list[str]) -> dict:
    """Return a per-claim report for every sentence that states a figure.

    `sources[i]` is the full text of citation `[i + 1]`.
    """
    claims: list[Claim] = []
    for sentence, cites in _claims(answer):
        figures = _figures(_CITATION.sub("", sentence))
        if not figures:
            continue
        claim = Claim(text=sentence, citations=cites, figures=sorted(figures))
        cited_text = " ".join(sources[c - 1] for c in cites if 0 < c <= len(sources))
        available = _figures(cited_text)
        claim.missing = sorted(f for f in figures if f not in available) if cites else []
        claims.append(claim)

    return {
        "checked": len(claims),
        "verified": sum(c.status == "verified" for c in claims),
        "claims": [asdict(c) | {"status": c.status} for c in claims],
    }
