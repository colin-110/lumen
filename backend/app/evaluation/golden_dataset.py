"""Golden retrieval-evaluation dataset.

Small, hand-authored fixture corpus (~15 short documents, one chunk each)
plus a set of questions with known-correct document(s), used to measure
retrieval quality independent of the LLM — no generation, no API cost.

Deliberately mixes two question styles so the strategy comparison in
`run.py` actually differentiates dense vs. sparse vs. hybrid instead of
just agreeing with itself:
  - keyword-heavy questions that reuse exact identifiers/terms from the
    source text (favors BM25/sparse)
  - paraphrased questions that never repeat the source's exact wording
    (favors dense embeddings)

Extend this by adding entries to DOCUMENTS and QUESTIONS — nothing else
needs to change; `run.py` re-ingests the full set on every run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenDocument:
    doc_key: str
    filename: str
    text: str


@dataclass(frozen=True)
class GoldenQuestion:
    question: str
    relevant_doc_keys: list[str] = field(default_factory=list)
    style: str = "paraphrase"  # "keyword" or "paraphrase" — see module docstring


DOCUMENTS: list[GoldenDocument] = [
    GoldenDocument(
        "billing",
        "billing_migration.txt",
        "The BillingCore migration moves invoice generation to the new payments "
        "provider. Invoice INV-2291 was the first production invoice issued under "
        "the new system. The cutover is scheduled for the first week of Q2.",
    ),
    GoldenDocument(
        "parental_leave",
        "parental_leave_policy.txt",
        "New parents, including adoptive and foster parents, may take 16 weeks of "
        "fully paid leave following the arrival of a child. Leave can be split "
        "into two blocks within the first year.",
    ),
    GoldenDocument(
        "security_patch",
        "security_advisory.txt",
        "CVE-2024-9981 was patched in the March security release. The "
        "vulnerability allowed unauthenticated access to internal admin routes "
        "and has been rated critical severity.",
    ),
    GoldenDocument(
        "finance_q3",
        "finance_q3_summary.txt",
        "Revenue for the third quarter reached $1.2 million, up 18% from the "
        "prior quarter. Gross margin held steady at 62%.",
    ),
    GoldenDocument(
        "onboarding",
        "new_hire_onboarding.txt",
        "New employees should complete laptop setup, badge activation, and the "
        "benefits enrollment form during their first three days. A manager "
        "check-in is scheduled for the end of week one.",
    ),
    GoldenDocument(
        "vpn_setup",
        "vpn_setup_guide.txt",
        "The corporate VPN uses WireGuard and listens on port 51820. Client "
        "configuration files are issued by IT and expire after 180 days.",
    ),
    GoldenDocument(
        "expense_policy",
        "expense_reimbursement_policy.txt",
        "Meal expenses while traveling on company business are capped at $75 per "
        "day. Receipts are required for any single expense over $25.",
    ),
    GoldenDocument(
        "incident_4471",
        "incident_report_4471.txt",
        "Incident INC-4471 caused a partial outage of the checkout service "
        "lasting 47 minutes. Root cause was a misconfigured connection pool "
        "limit after a routine deploy.",
    ),
    GoldenDocument(
        "perf_review",
        "performance_review_cycle.txt",
        "Formal performance reviews are conducted twice a year, in April and "
        "October. Managers submit written feedback one week before each review "
        "period closes.",
    ),
    GoldenDocument(
        "api_ratelimit",
        "api_rate_limits.txt",
        "Each API key is limited to 1000 requests per minute. Requests beyond "
        "the limit receive an HTTP 429 response with a Retry-After header.",
    ),
    GoldenDocument(
        "data_retention",
        "data_retention_policy.txt",
        "Application logs are retained for 90 days before automatic deletion. "
        "Audit logs covering account access are retained for 3 years.",
    ),
    GoldenDocument(
        "travel_policy",
        "business_travel_policy.txt",
        "Employees should book economy class for flights under six hours. "
        "Flights longer than six hours may be booked in premium economy with "
        "manager approval.",
    ),
    GoldenDocument(
        "equipment_policy",
        "equipment_refresh_policy.txt",
        "Company laptops are refreshed on a three-year cycle. Employees may "
        "request an earlier replacement if hardware failure is confirmed by IT.",
    ),
    GoldenDocument(
        "referral_bonus",
        "employee_referral_program.txt",
        "Employees who refer a successful hire receive a $2,000 bonus, paid "
        "after the new hire completes 90 days of employment.",
    ),
    GoldenDocument(
        "oncall_rotation",
        "oncall_rotation_policy.txt",
        "Primary on-call engineers carry the pager for one full week. A backup "
        "on-call engineer is assigned each rotation in case the primary is "
        "unreachable.",
    ),
]

QUESTIONS: list[GoldenQuestion] = [
    GoldenQuestion("What invoice number was first issued under the new billing system?", ["billing"], "keyword"),
    GoldenQuestion("How much paid time off do new parents get?", ["parental_leave"], "paraphrase"),
    GoldenQuestion("Which CVE was fixed in the March security release?", ["security_patch"], "keyword"),
    GoldenQuestion("What was the revenue figure last quarter and how did it change?", ["finance_q3"], "paraphrase"),
    GoldenQuestion("What should a new employee finish during their first few days?", ["onboarding"], "paraphrase"),
    GoldenQuestion("What port does the WireGuard VPN listen on?", ["vpn_setup"], "keyword"),
    GoldenQuestion("What's the daily cap for meals while traveling for work?", ["expense_policy"], "paraphrase"),
    GoldenQuestion("How long did incident INC-4471 last?", ["incident_4471"], "keyword"),
    GoldenQuestion("How often does the company formally evaluate employee performance?", ["perf_review"], "paraphrase"),
    GoldenQuestion("What's the per-minute request limit for an API key?", ["api_ratelimit"], "keyword"),
    GoldenQuestion("How long are application logs kept before they're deleted?", ["data_retention"], "paraphrase"),
    GoldenQuestion("What travel class should be used for short flights?", ["travel_policy"], "paraphrase"),
    GoldenQuestion("How often do employees get a new company laptop?", ["equipment_policy"], "paraphrase"),
    GoldenQuestion("What's the referral bonus amount and when is it paid out?", ["referral_bonus"], "keyword"),
    GoldenQuestion("How long does a primary on-call shift last?", ["oncall_rotation"], "paraphrase"),
    # Multi-relevant: exercises Recall@k/NDCG on questions with more than one
    # correct source rather than just precision on a single hit.
    GoldenQuestion(
        "Which policies mention a specific dollar amount?",
        ["expense_policy", "referral_bonus", "finance_q3"],
        "paraphrase",
    ),
    GoldenQuestion(
        "Which documents reference a specific incident or vulnerability ID?",
        ["incident_4471", "security_patch"],
        "keyword",
    ),
]
