"""Document -> plain text extraction.

Uses PyMuPDF for PDF and python-docx for Word docs — both are pure/native
extensions with no external system binaries (no poppler, no tesseract),
which keeps container builds fast and avoids OCR flakiness for the common
"born-digital" document case. Scanned/image-only PDFs won't yield text;
that's a deliberate scope cut, not an oversight.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log"}


class UnsupportedDocumentError(Exception):
    pass


def extract_text(file_path: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix in _TEXT_EXTENSIONS:
        return _extract_plain_text(file_path)

    # Last resort: try decoding as text before giving up, since some plain
    # text files arrive without a recognized extension.
    try:
        return _extract_plain_text(file_path)
    except UnicodeDecodeError as exc:
        raise UnsupportedDocumentError(f"Unsupported file type: {suffix or '(none)'}") from exc


def _extract_pdf(file_path: str) -> str:
    parts = []
    with fitz.open(file_path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n\n".join(parts)


def _extract_docx(file_path: str) -> str:
    doc = DocxDocument(file_path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n\n".join(parts)


def _extract_plain_text(file_path: str) -> str:
    with open(file_path, encoding="utf-8") as f:
        return f.read()
