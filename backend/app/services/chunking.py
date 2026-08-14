"""Structure-aware text splitter.

Documents are divided at headings first, then each section is chunked with the
usual recursive character split (paragraph, line, sentence, word, character)
inside its own budget. Two things this buys over splitting the whole document
flat:

  * A chunk never spans two sections, so it can't mix the tail of "Fees and
    Charges" with the head of "Payment Terms" — a chunk that then answered
    neither question well.

  * Every chunk carries its heading. A chunk from the middle of a long section
    otherwise reaches the embedder and the model as orphaned prose: "...billed
    at $80 per TB", with nothing indicating it concerns egress overage. The
    heading travels with it, which helps the dense embedding match and lets the
    model attribute the fact correctly.

Text with no detectable structure (plain prose, OCR output) falls back to the
original flat behaviour rather than inventing headings.

Written out rather than imported because this is the only thing the project
would have needed `langchain` for. Nothing else here uses it: conversation
state is persisted in Postgres via our own models, and litellm is called
directly. See the note in pyproject.toml.
"""

from __future__ import annotations

import re

_DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

# Heading shapes that actually occur in the documents this ingests: markdown
# ATX headings, numbered/lettered contract clauses, and short ALL-CAPS lines
# used as headers in exported PDFs and DOCX.
_HEADING_PATTERNS = (
    re.compile(r"^\s{0,3}#{1,6}\s+\S"),                     # "## Payment Terms"
    re.compile(r"^\s{0,3}\d+(\.\d+)*[.)]\s+\S"),            # "3. Payment Terms", "3.1) ..."
    re.compile(r"^\s{0,3}(?:article|section|clause|appendix|schedule)\s+[\dIVXivx]+", re.IGNORECASE),
    re.compile(r"^\s{0,3}[A-Z][A-Z0-9 &/,'()-]{3,60}$"),    # "PAYMENT TERMS"
)
# A heading is a short standalone line. Anything longer is prose that merely
# happens to start with a number ("1990 was the year the company ...").
_MAX_HEADING_CHARS = 90


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return False
    is_markdown = bool(re.match(r"^\s{0,3}#{1,6}\s", stripped))
    if not is_markdown and stripped.endswith((".", ",", ";", ":")):
        # Sentences end in punctuation, headings generally don't; a trailing
        # colon is a label ("Note:"), which is prose for our purposes.
        return False
    return any(p.match(stripped) for p in _HEADING_PATTERNS)


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split into (heading, body) pairs.

    Text appearing before the first heading is kept with an empty heading
    rather than dropped.
    """
    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in text.splitlines():
        if _is_heading(line):
            if body or heading:
                sections.append((heading, "\n".join(body).strip()))
            heading = line.strip().lstrip("#").strip()
            body = []
        else:
            body.append(line)
    if body or heading:
        sections.append((heading, "\n".join(body).strip()))
    return [(h, b) for h, b in sections if b or h]


def split_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    separators: list[str] | None = None,
) -> list[str]:
    """Split `text` into chunks of at most roughly `chunk_size` characters.

    Structure is applied first: the text is divided at headings, then each
    section is chunked independently, so a chunk never spans two sections.
    Each chunk is prefixed with its heading.

    That prefix is the point. A chunk taken from the middle of a long section
    otherwise reaches the embedder and the model as orphaned prose — "...billed
    at $80 per TB" with nothing saying it concerns egress overage. Carrying the
    heading improves both the dense embedding and the model's ability to
    attribute the fact.
    """
    text = text.strip()
    if not text:
        return []
    seps = separators or _DEFAULT_SEPARATORS

    sections = _split_into_sections(text)
    # Nothing detectable (plain prose, OCR output): behave exactly as the flat
    # splitter did rather than inventing structure that isn't there.
    if len(sections) <= 1 and not (sections and sections[0][0]):
        return _merge_with_overlap(_split_recursive(text, seps, chunk_size), chunk_size, chunk_overlap)

    chunks: list[str] = []
    for heading, body in sections:
        prefix = f"{heading}\n" if heading else ""
        # Reserve room for the prefix so a chunk plus its heading still lands
        # near chunk_size instead of overshooting it. The floor is
        # proportional rather than a fixed 200, which silently ignored any
        # chunk_size below 200 — a caller asking for 120-character chunks
        # got 200-character ones with no indication why.
        budget = max(chunk_size // 4, chunk_size - len(prefix))
        pieces = (
            _merge_with_overlap(_split_recursive(body, seps, budget), budget, chunk_overlap)
            if body
            else []
        )
        if not pieces:
            # A heading with no body still carries retrievable meaning.
            if heading:
                chunks.append(heading)
            continue
        chunks.extend(f"{prefix}{piece}" for piece in pieces)
    return chunks


def _split_recursive(text: str, separators: list[str], chunk_size: int) -> list[str]:
    """Split into pieces of at most `chunk_size`, keeping every character.

    Each piece carries the separator that followed it, so concatenating the
    pieces reproduces the input exactly. `str.split` discards the separator,
    and the previous version rejoined pieces with a single space — which for
    the ". ", "? " and "! " separators meant the sentence-ending punctuation
    was deleted from the stored chunk. A paragraph long enough to need
    splitting reached the embedder, the reranker and the model as one
    run-on sentence: "...about topic 1 Sentence number 2 says...". Measured
    on a plain 11-sentence paragraph, 10 of the 11 periods were lost.
    """
    if len(text) <= chunk_size:
        return [text] if text else []

    sep, remaining_seps = separators[0], separators[1:]
    if sep == "":
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    parts = text.split(sep)
    if len(parts) == 1:
        # This separator doesn't occur in the text; fall through to the next one.
        if not remaining_seps:
            return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        return _split_recursive(text, remaining_seps, chunk_size)

    # Reattach the separator to the part it followed. The final part had no
    # trailing separator in the source, so it stays as-is.
    parts = [p + sep for p in parts[:-1]] + [parts[-1]]

    results: list[str] = []
    for part in parts:
        if not part:
            continue
        if len(part) > chunk_size and remaining_seps:
            results.extend(_split_recursive(part, remaining_seps, chunk_size))
        elif len(part) > chunk_size:
            results.extend(part[i : i + chunk_size] for i in range(0, len(part), chunk_size))
        else:
            results.append(part)
    return results


def _merge_with_overlap(pieces: list[str], chunk_size: int, overlap: int) -> list[str]:
    """Greedily pack small pieces back together up to chunk_size, carrying
    a tail of `overlap` characters from one chunk into the next so context
    isn't lost at a hard boundary.

    Pieces are concatenated with no joining character: each already carries
    the separator it was split on, so the original text is reconstructed
    verbatim rather than approximated with spaces.
    """
    if not pieces:
        return []

    merged: list[str] = []
    current = ""
    for piece in pieces:
        candidate = current + piece
        if len(candidate) <= chunk_size or not current:
            current = candidate
            continue

        merged.append(current.strip())
        # Carry an overlap tail from the chunk just emitted. This one *is* a
        # synthetic join — the tail is duplicated context, not a continuation
        # of the source — so a space between it and the new piece is correct.
        if overlap > 0:
            tail = merged[-1][-overlap:].strip()
            current = f"{tail} {piece}" if tail else piece
        else:
            current = piece

    if current.strip():
        merged.append(current.strip())
    return merged
