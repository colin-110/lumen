from app.services.retrieval import RetrievedChunk, allocate_fairly


def chunk(doc: str, idx: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{doc}-{idx}",
        document_id=doc,
        filename=f"{doc}.txt",
        text=f"text {doc} {idx}",
        score=score,
    )


def docs_of(chunks) -> list[str]:
    return [c.document_id for c in chunks]


def test_long_document_cannot_monopolise_the_budget():
    # The regression this exists for: a long contract out-scoring a short
    # invoice on every chunk would otherwise fill the whole context.
    ranked = [chunk("contract", i, 5.0 - i * 0.1) for i in range(6)] + [chunk("invoice", 0, 1.0)]
    selected = allocate_fairly(ranked, limit=6)
    assert "invoice" in docs_of(selected)


def test_diverges_from_plain_top_k_on_the_measured_real_case():
    # Reproduces an actual trace: asking a 7-chunk contract and a 1-chunk
    # invoice about "service levels, liability and termination" ranked six
    # contract chunks above the invoice's only chunk. Plain top-6 therefore
    # dropped the invoice entirely, leaving the model unable to even report
    # that the invoice says nothing about those terms.
    ranked = [
        chunk("contract", 0, -0.62),
        chunk("contract", 1, -3.48),
        chunk("contract", 2, -10.17),
        chunk("contract", 3, -11.15),
        chunk("contract", 4, -11.16),
        chunk("contract", 5, -11.40),
        chunk("invoice", 0, -11.42),
    ]
    plain_top_k = ranked[:6]
    assert "invoice" not in docs_of(plain_top_k)  # the bug

    fair = allocate_fairly(ranked, limit=6)
    assert "invoice" in docs_of(fair)  # the fix
    assert len(fair) == 6  # without shrinking the context budget


def test_every_document_contributes_before_any_contributes_twice():
    ranked = [
        chunk("a", 0, 9.0),
        chunk("a", 1, 8.0),
        chunk("a", 2, 7.0),
        chunk("b", 0, 6.0),
        chunk("c", 0, 5.0),
    ]
    selected = allocate_fairly(ranked, limit=4)
    # First pass takes a[0], b[0], c[0]; only then does "a" get a second slot.
    assert docs_of(selected) == ["a", "b", "c", "a"]


def test_most_relevant_document_still_leads_the_context():
    ranked = [chunk("b", 0, 9.0), chunk("a", 0, 1.0)]
    assert docs_of(allocate_fairly(ranked, limit=2)) == ["b", "a"]


def test_within_a_document_original_order_is_preserved():
    ranked = [chunk("a", 0, 9.0), chunk("a", 1, 8.0), chunk("a", 2, 7.0)]
    selected = allocate_fairly(ranked, limit=3)
    assert [c.chunk_id for c in selected] == ["a-0", "a-1", "a-2"]


def test_respects_the_limit():
    ranked = [chunk("a", i, 9.0 - i) for i in range(10)]
    assert len(allocate_fairly(ranked, limit=4)) == 4


def test_returns_everything_when_limit_exceeds_available_chunks():
    ranked = [chunk("a", 0, 9.0), chunk("b", 0, 8.0)]
    assert len(allocate_fairly(ranked, limit=99)) == 2


def test_uneven_document_sizes_drain_without_dropping_chunks():
    ranked = [chunk("a", 0, 9.0), chunk("a", 1, 8.0), chunk("a", 2, 7.0), chunk("b", 0, 6.0)]
    selected = allocate_fairly(ranked, limit=99)
    # "b" is exhausted after one pass; "a" keeps filling rather than stalling.
    assert sorted(c.chunk_id for c in selected) == ["a-0", "a-1", "a-2", "b-0"]


def test_empty_input_and_zero_limit_are_safe():
    assert allocate_fairly([], limit=5) == []
    assert allocate_fairly([chunk("a", 0, 1.0)], limit=0) == []


class TestScoreFloorNeverStarvesTheContext:
    """The cross-encoder scores anything that isn't a direct answer steeply
    negative. Applying the floor alone left broad questions ("summarise
    everything") with a single chunk, so the model could only ever discuss one
    document and it looked like retrieval had failed.
    """

    def test_broad_question_keeps_several_documents_despite_low_scores(self):
        from app.core.config import settings
        from app.services.retrieval import select_within_floor as apply_floor

        # Real shape from a trace: one strong hit, the rest topically related
        # but scored far below the -6.0 floor.
        ranked = [
            chunk("expenses", 0, 4.23),
            chunk("perdiem", 0, -9.74),
            chunk("travel", 0, -10.48),
            chunk("vpn", 0, -11.15),
            chunk("incident", 0, -11.20),
        ]
        kept = apply_floor(ranked)
        assert len(kept) >= settings.MIN_CONTEXT_CHUNKS
        assert len({c.document_id for c in kept}) > 1  # not a single document

    def test_narrow_question_still_trims_irrelevant_chunks(self):
        from app.services.retrieval import select_within_floor as apply_floor

        # Plenty above the floor: the floor should do its job and trim the rest.
        ranked = [chunk(f"d{i}", 0, 5.0 - i * 0.1) for i in range(6)] + [
            chunk("junk", 0, -11.0)
        ]
        kept = apply_floor(ranked)
        assert all(c.document_id != "junk" for c in kept)
