"""Document -> text extraction.

This module is the most testable file in the project — bytes in, text out,
no services — and had no tests at all. Everything downstream (chunking,
embedding, retrieval, the answer itself) is built on whatever it returns, so
a silent decoding failure here degrades every layer above it without
surfacing anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.document_parser import (
    UnsupportedDocumentError,
    _extract_plain_text,
    _looks_binary,
    _render_table,
    extract_text,
)


def _write(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


class TestEncodingTolerance:
    """A strict UTF-8 codec rejected any CSV exported from Excel. The file was
    recorded as permanently unprocessable over a handful of accented
    characters."""

    def test_plain_utf8(self, tmp_path):
        p = _write(tmp_path, "a.txt", b"hello world")
        assert _extract_plain_text(p) == "hello world"

    def test_utf8_with_bom_does_not_leak_the_bom(self, tmp_path):
        p = _write(tmp_path, "a.txt", b"\xef\xbb\xbfInvoice Total")
        text = _extract_plain_text(p)
        assert text == "Invoice Total"
        assert "﻿" not in text

    def test_cp1252_smart_quotes_decode(self, tmp_path):
        # 0x93/0x94 are curly quotes in cp1252 and invalid UTF-8.
        p = _write(tmp_path, "a.csv", b"\x93Payment Terms\x94,NET 30")
        text = _extract_plain_text(p)
        assert "Payment Terms" in text
        assert "NET 30" in text

    def test_latin1_accents_decode(self, tmp_path):
        p = _write(tmp_path, "a.txt", "café résumé".encode("latin-1"))
        assert "caf" in _extract_plain_text(p)

    def test_decoding_never_raises(self, tmp_path):
        """Whatever the bytes, extraction returns text rather than failing —
        a document with a few replacement characters is still searchable."""
        p = _write(tmp_path, "a.txt", bytes(range(1, 256)))
        assert isinstance(_extract_plain_text(p), str)


class TestBinaryDetection:
    """`_extract_plain_text` falls through to latin-1, which accepts any byte
    sequence, so it can no longer signal "this isn't text". Without an
    explicit check an unknown binary would ingest as thousands of chunks of
    mojibake."""

    def test_a_nul_byte_marks_binary(self, tmp_path):
        assert _looks_binary(_write(tmp_path, "x.bin", b"MZ\x00\x00\x90\x00"))

    def test_plain_text_is_not_binary(self, tmp_path):
        assert not _looks_binary(_write(tmp_path, "x.txt", b"just some text\n"))

    def test_an_unknown_binary_extension_is_rejected(self, tmp_path):
        p = _write(tmp_path, "payload.bin", b"\x7fELF\x00\x00\x00")
        with pytest.raises(UnsupportedDocumentError):
            extract_text(p, "payload.bin")

    def test_an_unknown_text_extension_still_extracts(self, tmp_path):
        """Some plain-text files arrive with no recognised extension."""
        p = _write(tmp_path, "notes.rst", b"Release notes\n=============\n")
        assert "Release notes" in extract_text(p, "notes.rst")


class TestDispatch:
    def test_txt_md_and_csv_route_to_plain_text(self, tmp_path):
        for name in ("a.txt", "a.md", "a.csv", "a.json", "a.log"):
            p = _write(tmp_path, name, b"content-marker")
            assert "content-marker" in extract_text(p, name)

    def test_extension_matching_is_case_insensitive(self, tmp_path):
        p = _write(tmp_path, "A.TXT", b"upper case extension")
        assert "upper case extension" in extract_text(p, "A.TXT")


class _Cell:
    def __init__(self, text: str) -> None:
        self.text = text


class _Row:
    def __init__(self, *values: str) -> None:
        self.cells = [_Cell(v) for v in values]


class _Table:
    def __init__(self, *rows: _Row) -> None:
        self.rows = list(rows)


class TestTableRendering:
    """Flattening every row to "a | b | c" dropped which column a value was
    in, so a chunk from the middle of a table reached the model as bare
    numbers with nothing saying what they measured."""

    def test_the_header_row_is_marked(self):
        rendered = _render_table(
            _Table(_Row("Item", "Qty", "Price"), _Row("Widget", "12", "$4.00"))
        )
        lines = rendered.splitlines()
        assert lines[0] == "Item | Qty | Price"
        assert set(lines[1].replace(" ", "").split("|")) == {"---"}
        assert lines[2] == "Widget | 12 | $4.00"

    def test_a_single_row_table_has_no_separator(self):
        assert _render_table(_Table(_Row("just", "one"))) == "just | one"

    def test_empty_rows_are_dropped(self):
        rendered = _render_table(_Table(_Row("A", "B"), _Row("", ""), _Row("1", "2")))
        assert "1 | 2" in rendered
        assert "\n\n" not in rendered

    def test_a_fully_empty_table_renders_nothing(self):
        assert _render_table(_Table(_Row("", ""))) == ""

    def test_newlines_inside_a_cell_do_not_break_the_row(self):
        rendered = _render_table(_Table(_Row("Multi\nline", "ok")))
        assert rendered.count("\n") == 0
        assert rendered == "Multi line | ok"


class TestDocx:
    def test_paragraphs_and_tables_both_survive(self, tmp_path):
        docx = pytest.importorskip("docx")

        document = docx.Document()
        document.add_paragraph("Payment Terms")
        document.add_paragraph("")  # blank paragraphs should not add noise
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Item"
        table.cell(0, 1).text = "Amount"
        table.cell(1, 0).text = "Retainer"
        table.cell(1, 1).text = "$4,500.00"
        path = tmp_path / "contract.docx"
        document.save(str(path))

        text = extract_text(str(path), "contract.docx")
        assert "Payment Terms" in text
        assert "Item | Amount" in text
        assert "Retainer | $4,500.00" in text
