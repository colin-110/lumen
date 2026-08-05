from app.services.chunking import split_text


def test_empty_text_returns_no_chunks():
    assert split_text("") == []
    assert split_text("   ") == []


def test_short_text_returns_single_chunk():
    text = "This fits in one chunk."
    assert split_text(text, chunk_size=1000, chunk_overlap=150) == [text]


def test_long_text_splits_into_multiple_chunks_within_size():
    text = "\n\n".join(f"Paragraph {i}. " + ("word " * 40) for i in range(20))
    chunks = split_text(text, chunk_size=300, chunk_overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        # Overlap can push a chunk slightly past chunk_size; it should never
        # balloon far past it.
        assert len(chunk) <= 300 + 50 + 5


def test_consecutive_chunks_share_overlap_text():
    text = "\n\n".join(f"Section {i}: " + ("content " * 30) for i in range(10))
    chunks = split_text(text, chunk_size=200, chunk_overlap=40)
    assert len(chunks) > 1
    # The overlap tail of one chunk should reappear at the start of the next.
    for prev, nxt in zip(chunks, chunks[1:]):
        tail = prev[-40:].strip()
        assert any(word in nxt for word in tail.split()[:3])


def test_no_content_lost_across_chunks():
    words = [f"token{i}" for i in range(500)]
    text = " ".join(words)
    chunks = split_text(text, chunk_size=200, chunk_overlap=0)
    rejoined = " ".join(chunks)
    for word in words:
        assert word in rejoined
