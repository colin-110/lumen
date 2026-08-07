"""Structure-aware chunking.

Flat character chunking produced two failures this locks down: chunks that
straddled a section boundary and so answered neither section's question well,
and chunks from the middle of a section that reached the embedder as orphaned
prose with nothing indicating what they were about.
"""

from app.services.chunking import _is_heading, _split_into_sections, split_text

CONTRACT = """Master Services Agreement

1. Fees and Charges
The agreed monthly fee is $4,500 USD, billed in arrears. Any overage beyond
10TB of egress is billed at $80 per TB.

2. Payment Terms
Payment terms are NET 30 from invoice date. Late payments accrue interest at
1.5% per month.

3. Termination
Either party may terminate for material breach not remedied within 30 days.
"""


class TestHeadingDetection:
    def test_recognises_markdown_numbered_and_caps_headings(self):
        assert _is_heading("## Payment Terms")
        assert _is_heading("3. Termination")
        assert _is_heading("3.1) Late Payment")
        assert _is_heading("PAYMENT TERMS")
        assert _is_heading("Section 4")

    def test_prose_is_not_mistaken_for_a_heading(self):
        # Starts with a number but is a sentence.
        assert not _is_heading("1990 was the year the company was founded.")
        # Ends in punctuation.
        assert not _is_heading("Note:")
        # Too long to be a heading.
        assert not _is_heading("2. " + "word " * 40)
        assert not _is_heading("")


class TestSectioning:
    def test_splits_at_headings_and_keeps_the_preamble(self):
        sections = _split_into_sections(CONTRACT)
        headings = [h for h, _ in sections]
        assert "Fees and Charges" in " ".join(headings)
        assert "Payment Terms" in " ".join(headings)
        assert "Termination" in " ".join(headings)


class TestSplitText:
    def test_every_chunk_carries_its_heading(self):
        chunks = split_text(CONTRACT, chunk_size=200, chunk_overlap=20)
        payment = [c for c in chunks if "NET 30" in c]
        assert payment, "the payment clause should survive chunking"
        # The fact arrives with its heading attached rather than orphaned.
        assert any("Payment Terms" in c for c in payment)

    def test_a_chunk_never_spans_two_sections(self):
        chunks = split_text(CONTRACT, chunk_size=2000, chunk_overlap=0)
        for c in chunks:
            mixed = ("NET 30" in c) and ("$80 per TB" in c)
            assert not mixed, "fees and payment terms must not share a chunk"

    def test_no_content_is_lost(self):
        chunks = split_text(CONTRACT, chunk_size=180, chunk_overlap=20)
        joined = " ".join(chunks)
        for fact in ("$4,500", "$80 per TB", "NET 30", "1.5%", "30 days"):
            assert fact in joined

    def test_unstructured_prose_falls_back_to_flat_splitting(self):
        prose = " ".join(f"sentence number {i}." for i in range(200))
        chunks = split_text(prose, chunk_size=300, chunk_overlap=50)
        assert len(chunks) > 1
        # Nothing invented: no heading prefix appears where there is no heading.
        assert all(not c.startswith("#") for c in chunks)

    def test_respects_chunk_size_including_the_prefix(self):
        chunks = split_text(CONTRACT, chunk_size=250, chunk_overlap=20)
        for c in chunks:
            assert len(c) <= 250 + 20 + 80  # budget + overlap + heading slack

    def test_empty_and_whitespace_input(self):
        assert split_text("") == []
        assert split_text("   \n  ") == []

    def test_heading_with_no_body_is_kept(self):
        chunks = split_text("1. Definitions\n\n2. Scope\nThe scope is broad.")
        assert any("Definitions" in c for c in chunks)
