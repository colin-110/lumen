"""Which documents a question names, for automatic comparison scoping."""

from __future__ import annotations

from app.services.document_mentions import named_documents

DOCS = [
    ("travel", "acme-travel-policy.txt"),
    ("msa", "northwind-services-agreement.txt"),
    ("inv", "northwind-invoice-INV-2026-0412.txt"),
    ("handbook", "employee-handbook-2026.pdf"),
]


def test_a_comparison_names_both_documents():
    q = "Does the Northwind invoice match the services agreement?"
    assert sorted(named_documents(q, DOCS)) == ["inv", "msa"]


def test_plurals_still_match():
    assert "msa" in named_documents("What do the Northwind services agreements say?", DOCS)


def test_an_invoice_number_alone_identifies_the_invoice():
    assert named_documents("Is 0412 overdue?", DOCS) == ["inv"]


def test_a_shared_vendor_name_alone_is_not_enough():
    # "Northwind" appears in two filenames; on its own it names neither.
    assert named_documents("What does Northwind charge?", DOCS) == []


def test_a_bare_year_does_not_pin_documents():
    assert named_documents("What changed in 2026?", DOCS) == []


def test_generic_words_do_not_match():
    assert named_documents("Summarise the document and the file", DOCS) == []


def test_a_question_without_names_matches_nothing():
    assert named_documents("What is the hotel cap in London?", DOCS) == []
