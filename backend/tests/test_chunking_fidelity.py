"""The splitter must not alter the text it splits.

`str.split(sep)` discards the separator, and chunks were rejoined with a
single space. For the "\\n" separator that is harmless. For ". ", "? " and
"! " it deleted the sentence-ending punctuation: a paragraph long enough to
need splitting was stored, embedded, reranked and shown to the model as one
run-on sentence.

The pre-existing fidelity tests could not catch it — one used
space-separated tokens (no sentence separators involved) and the other
asserted that particular facts appeared somewhere in the output, which they
did.
"""

from __future__ import annotations

from app.services.chunking import split_text


def _no_whitespace(text: str) -> str:
    return "".join(text.split())


class TestSeparatorsSurvive:
    def test_sentence_punctuation_is_not_deleted(self):
        paragraph = " ".join(
            f"Sentence number {i} says something about topic {i}." for i in range(1, 12)
        )
        chunks = split_text(paragraph, chunk_size=200, chunk_overlap=0)

        assert len(chunks) > 1, "this input must actually split for the test to mean anything"
        assert sum(c.count(".") for c in chunks) == paragraph.count(".")

    def test_question_and_exclamation_marks_survive(self):
        paragraph = " ".join(
            f"Is clause {i} enforceable? It certainly is! " for i in range(1, 20)
        ).strip()
        chunks = split_text(paragraph, chunk_size=150, chunk_overlap=0)

        assert len(chunks) > 1
        assert sum(c.count("?") for c in chunks) == paragraph.count("?")
        assert sum(c.count("!") for c in chunks) == paragraph.count("!")

    def test_text_is_reconstructed_exactly_with_no_overlap(self):
        paragraph = " ".join(
            f"Clause {i}. The supplier shall deliver within {i} days." for i in range(1, 30)
        )
        chunks = split_text(paragraph, chunk_size=180, chunk_overlap=0)
        assert _no_whitespace("".join(chunks)) == _no_whitespace(paragraph)

    def test_a_decimal_amount_is_not_mangled(self):
        """"$4,500.00 is due" must not become "$4,500 00 is due"."""
        body = (
            "The total contract value is $4,500.00 payable in advance. "
            "A late fee of 1.5% per month applies to any overdue balance. "
        ) * 6
        chunks = split_text(body, chunk_size=200, chunk_overlap=0)
        joined = " ".join(chunks)
        assert "$4,500.00" in joined
        assert "1.5%" in joined


class TestOverlapStillWorks:
    def test_consecutive_chunks_share_their_boundary_text(self):
        paragraph = " ".join(f"Section {i} contains material detail." for i in range(1, 40))
        chunks = split_text(paragraph, chunk_size=200, chunk_overlap=50)

        assert len(chunks) > 2
        for previous, following in zip(chunks, chunks[1:]):
            tail_words = previous[-50:].strip().split()[:3]
            assert any(word in following for word in tail_words)

    def test_chunks_stay_near_the_requested_size(self):
        paragraph = " ".join(f"Sentence {i} is here." for i in range(1, 200))
        overlap = 40
        chunks = split_text(paragraph, chunk_size=250, chunk_overlap=overlap)
        for chunk in chunks:
            assert len(chunk) <= 250 + overlap + 5


class TestSmallChunkSizeIsHonoured:
    def test_a_requested_size_below_200_is_not_silently_ignored(self):
        """`budget = max(200, chunk_size - len(prefix))` overrode any
        chunk_size under 200, so a caller asking for 120 got 200."""
        document = "## Overview\n\n" + " ".join(f"word{i}" for i in range(300))
        chunks = split_text(document, chunk_size=120, chunk_overlap=10)
        assert len(chunks) > 1
        assert max(len(c) for c in chunks) < 200
