"""Document -> plain text extraction.

Uses PyMuPDF for PDF and python-docx for Word docs — both are pure/native
extensions with no external system binaries, which keeps container builds
fast and avoids OCR flakiness for the common "born-digital" document case.

Scanned/image-only PDF pages have no text layer for PyMuPDF to read, so
each page that yields near-nothing falls back to Tesseract OCR: rendered
to an image at OCR_DPI and passed through pytesseract. This is a per-page
fallback (not whole-document), so a PDF mixing real text pages with
scanned ones only pays the (much slower) OCR cost on the pages that
actually need it.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument

from app.core.config import settings

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
    ocr_pages = 0
    with fitz.open(file_path) as doc:
        for page in doc:
            text = page.get_text("text")
            if settings.OCR_ENABLED and len(text.strip()) < settings.OCR_MIN_CHARS_PER_PAGE:
                ocr_text = _ocr_page(page)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
                    ocr_pages += 1
            parts.append(text)
    if ocr_pages:
        logger.info("OCR fallback used on %d page(s) of %s", ocr_pages, file_path)
    return "\n\n".join(parts)


def _ocr_page(page: fitz.Page) -> str:
    """Render a page to an image and run Tesseract on it. Imported lazily so
    a missing/broken tesseract install only breaks OCR, not every upload —
    born-digital PDFs (the common case) never touch this code path."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("pytesseract/Pillow not installed; skipping OCR fallback")
        return ""

    try:
        pix = page.get_pixmap(dpi=settings.OCR_DPI)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(image)
    except Exception:
        logger.warning("OCR fallback failed for a page; leaving it blank", exc_info=True)
        return ""


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
