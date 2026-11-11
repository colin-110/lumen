"""Figure checking: every number in a cited sentence must be in its source."""

from __future__ import annotations

from app.services.grounding import verify_figures

CONTRACT = "3. FEES\nThe monthly service fee is 4,200 USD. Late payments accrue 1.0% per month."
INVOICE = "1. Managed service, monthly fee ........ 4,500.00 USD\nPayment terms: Net 15 days."


def test_quoted_figures_are_verified_in_any_format():
    answer = "The contract fee is $4,200 per month [1], with 1% monthly interest [1]."
    report = verify_figures(answer, [CONTRACT])
    assert report["checked"] == 1 and report["verified"] == 1


def test_a_misquoted_figure_is_caught():
    report = verify_figures("The invoice charges 4,800 USD [2].", [CONTRACT, INVOICE])
    (claim,) = report["claims"]
    assert claim["status"] == "unverified" and claim["missing"] == ["4800"]


def test_each_sentence_is_checked_against_its_own_citations():
    answer = "The agreement says 4,200 USD [1]. The invoice says 4,500.00 USD [1]."
    statuses = [c["status"] for c in verify_figures(answer, [CONTRACT, INVOICE])["claims"]]
    assert statuses == ["verified", "unverified"]  # 4,500 is in source 2, not 1


def test_multiple_citations_pool_their_sources():
    answer = "It bills 4,500 against a fee of 4,200 [1, 2]."
    assert verify_figures(answer, [CONTRACT, INVOICE])["verified"] == 1


def test_list_markers_and_citation_numbers_are_not_figures():
    answer = "1. The invoice is due on net 15 terms [2]."
    (claim,) = verify_figures(answer, [CONTRACT, INVOICE])["claims"]
    assert claim["figures"] == ["15"] and claim["status"] == "verified"


def test_uncited_figures_are_reported_as_uncited():
    (claim,) = verify_figures("The fee rose by 300 USD.", [CONTRACT])["claims"]
    assert claim["status"] == "uncited"


def test_sentences_without_figures_are_skipped():
    assert (
        verify_figures("Both documents name the same parties [1, 2].", [CONTRACT])["checked"] == 0
    )


def test_out_of_range_citations_do_not_crash():
    (claim,) = verify_figures("The fee is 4,200 USD [9].", [CONTRACT])["claims"]
    assert claim["status"] == "unverified"


def test_reference_codes_are_not_figures():
    answer = "Invoice INV-2026-0412 does not match MSA-2026-017."
    assert verify_figures(answer, [CONTRACT])["checked"] == 0
