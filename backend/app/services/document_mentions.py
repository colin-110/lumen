"""Find the documents a question names, so comparisons scope themselves.

"Does the Northwind invoice match the services agreement?" names two
documents. Answered as an open question, retrieval ranked the contract's
boilerplate above its fee clause and the answer said the prices were missing;
answered with both documents pinned, every discrepancy was found. Pinning
used to require the user to know about the document picker. This module does
the pinning when the question itself names the documents.

Matching is deliberately conservative: a document counts as named only when
the question shares at least two distinctive words with its filename, or one
identifier such as an invoice number. A wrong match narrows retrieval to the
wrong documents, which is worse than not matching at all.
"""

from __future__ import annotations

import re

# Words that appear in filenames without telling documents apart.
_GENERIC = frozenset(
    {
        "a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by",
        "doc", "docs", "document", "file", "files", "pdf", "txt", "md", "docx", "csv",
        "json", "log", "final", "copy", "draft", "new", "old", "v1", "v2", "v3",
    }
)  # fmt: skip
_YEAR = re.compile(r"(19|20)\d\d")


def _words(text: str) -> set[str]:
    words = set()
    for raw in re.split(r"[^a-z0-9]+", text.lower()):
        if len(raw) < 2 or raw in _GENERIC:
            continue
        # Crude plural folding so "invoices" matches "invoice" and "services"
        # matches "service"; good enough for filenames, no stemmer dependency.
        words.add(raw[:-1] if len(raw) > 3 and raw.endswith("s") else raw)
    return words


def _is_identifier(word: str) -> bool:
    """Invoice/contract numbers ("0412", "inv2026") pin a document on their own.
    Bare years don't: "2026" appears in half the questions anyone asks."""
    return len(word) >= 4 and any(c.isdigit() for c in word) and not _YEAR.fullmatch(word)


def named_documents(question: str, documents: list[tuple[str, str]]) -> list[str]:
    """Return the ids of `documents` (id, filename) that `question` names."""
    asked = _words(question)
    named = []
    for doc_id, filename in documents:
        stem = filename.rsplit(".", 1)[0]
        shared = _words(stem) & asked
        strong = any(_is_identifier(w) for w in shared)
        if shared and (strong or len(shared) >= min(2, len(_words(stem)))):
            named.append(doc_id)
    return named
