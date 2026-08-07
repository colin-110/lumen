"""Guards the boundary between what the UI shows and what the model reads.

`SourceRef.snippet` is a 600-character preview for the citation hover card.
For a long time the prompt was built from that same field, so with
CHUNK_SIZE=1000 the model silently received only the first ~60% of every
retrieved chunk — retrieval would surface exactly the right passage and the
answer would still be "the context doesn't say".
"""

from app.core.config import settings
from app.services.agent import _build_sources, _format_context, _system_prompt_for
from app.services.retrieval import RetrievedChunk


def chunk(doc: str, text: str, score: float = 1.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{doc}-chunk",
        document_id=doc,
        filename=f"{doc}.txt",
        text=text,
        score=score,
    )


def test_full_chunk_text_reaches_the_prompt_not_the_600_char_preview():
    # A fact deliberately placed past the old truncation point.
    body = ("filler. " * 100) + "THE ACCESS CODE IS ZX-9931."
    assert len(body) > 600
    context = _format_context([chunk("doc", body)])
    assert "THE ACCESS CODE IS ZX-9931." in context


def test_prompt_is_not_truncated_at_any_chunk_size_we_index_at():
    body = "x" * settings.CHUNK_SIZE + "TAIL"
    assert "TAIL" in _format_context([chunk("doc", body)])


def test_ui_snippet_stays_truncated_so_the_payload_stays_small():
    body = "y" * 5000
    (source,) = _build_sources([chunk("doc", body)])
    assert len(source.snippet) == 600


def test_citation_indices_match_between_prompt_and_ui_sources():
    chunks = [chunk("a", "alpha"), chunk("b", "beta"), chunk("c", "gamma")]
    context = _format_context(chunks)
    sources = _build_sources(chunks)
    # The model is told [1],[2],[3]; the chips must be numbered identically or
    # a citation would point at the wrong document.
    assert [s.index for s in sources] == [1, 2, 3]
    for i, c in enumerate(chunks, start=1):
        assert f"[{i}] (source: {c.filename})" in context


def test_empty_retrieval_produces_an_explicit_no_context_message():
    assert "No relevant internal documents" in _format_context([])


def test_multi_document_guidance_only_added_when_documents_actually_differ():
    one_doc = _build_sources([chunk("a", "x"), chunk("a", "y")])
    two_docs = _build_sources([chunk("a", "x"), chunk("b", "y")])
    assert "MULTIPLE DIFFERENT DOCUMENTS" not in _system_prompt_for(one_doc)
    assert "MULTIPLE DIFFERENT DOCUMENTS" in _system_prompt_for(two_docs)
