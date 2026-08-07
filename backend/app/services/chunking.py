"""Recursive character text splitter.

A small reimplementation of the common "recursive character splitter"
pattern (split on paragraph, then line, then sentence, then word, then
character, backing off until pieces fit).

Written out rather than imported because this is the only thing the project
would have needed `langchain` for. Nothing else here uses it: conversation
state is persisted in Postgres via our own models, and litellm is called
directly. See the note in pyproject.toml.
"""

from __future__ import annotations

_DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]


def split_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    separators: list[str] | None = None,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    seps = separators or _DEFAULT_SEPARATORS
    raw_chunks = _split_recursive(text, seps, chunk_size)
    return _merge_with_overlap(raw_chunks, chunk_size, chunk_overlap)


def _split_recursive(text: str, separators: list[str], chunk_size: int) -> list[str]:
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
    isn't lost at a hard boundary."""
    if not pieces:
        return []

    merged: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            merged.append(current)
        current = piece[:chunk_size] if len(piece) > chunk_size else piece
        # carry overlap from the tail of the previous chunk
        if merged and overlap > 0:
            tail = merged[-1][-overlap:]
            current = f"{tail} {current}".strip()
    if current:
        merged.append(current)
    return merged
