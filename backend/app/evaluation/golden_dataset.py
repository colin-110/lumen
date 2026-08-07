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
    expected_answer: str = ""  # ground truth, used by the generation eval harness's LLM judge


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
    # --- multi-section documents -------------------------------------------
    # Every fixture above is a single chunk, which means chunking has no effect
    # on them and the harness cannot detect a chunking regression or
    # improvement. These two are long enough to split across several chunks and
    # are organised under headings, so structure-aware chunking is exercised:
    # the fact being asked about sits in the middle of a section, far from the
    # document's opening, and can only be retrieved well if the chunk carries
    # its heading.
    GoldenDocument(
        "msa_contract",
        "master_services_agreement.txt",
        "Master Services Agreement between Northwind Ltd and Acme Corp\n"
        "\n"
        "1. Scope of Services\n"
        "Northwind shall provide managed hosting for all production workloads, "
        "including provisioning, monitoring, patching and incident response. "
        "Services are delivered from the eu-west region unless otherwise agreed "
        "in writing. Capacity planning reviews occur quarterly and are "
        "accompanied by a written report to the customer's technical account "
        "manager. Change requests affecting scope must be documented and "
        "approved by both parties before any work commences.\n"
        "\n"
        "2. Fees and Charges\n"
        "The agreed monthly fee is $4,500 USD, billed in arrears. That fee "
        "covers up to 10TB of aggregate egress traffic per calendar month, "
        "measured at the edge. Any overage beyond 10TB is billed at $80 per "
        "terabyte, prorated to the nearest whole terabyte. Fees are exclusive "
        "of sales tax, VAT or withholding, which are added to each invoice as "
        "required by law.\n"
        "\n"
        "3. Payment Terms\n"
        "Payment terms are NET 30 from the invoice date. Invoices not disputed "
        "in writing within 10 business days of receipt are deemed accepted in "
        "full. Late payments accrue interest at 1.5% per month or the maximum "
        "permitted by law, whichever is lower. Disputed line items do not "
        "excuse payment of undisputed amounts on the same invoice.\n"
        "\n"
        "4. Service Levels\n"
        "Northwind commits to 99.9% monthly uptime measured at the load "
        "balancer, excluding maintenance windows notified five business days in "
        "advance. Credits of 10% of monthly fees apply for each full percentage "
        "point below target, capped at 50% of the monthly fee for any single "
        "month. Credits are the sole remedy for a missed service level and must "
        "be claimed within 30 days of the affected month.\n"
        "\n"
        "5. Termination\n"
        "Either party may terminate for material breach not remedied within 30 "
        "days of written notice. On termination the customer shall pay all fees "
        "accrued to the effective date. Migration assistance beyond the standard "
        "30 day handover is billed at $200 per hour under a separate statement "
        "of work.",
    ),
    GoldenDocument(
        "security_handbook",
        "security_handbook.txt",
        "Information Security Handbook\n"
        "\n"
        "1. Access Control\n"
        "All production access requires multi-factor authentication. Access is "
        "granted on a least-privilege basis and reviewed every quarter by the "
        "system owner. Shared accounts are prohibited. Access for departing "
        "staff is revoked within one hour of their final working day.\n"
        "\n"
        "2. Encryption Standards\n"
        "Data at rest is encrypted with AES-256. Data in transit uses TLS 1.3 "
        "or higher; TLS 1.2 is permitted only for legacy integrations with a "
        "documented exception. Encryption keys are rotated every 12 months and "
        "stored in a managed key service, never in source control.\n"
        "\n"
        "3. Incident Response\n"
        "Suspected incidents must be reported to the security team within one "
        "hour of discovery. The on-call security engineer triages within 30 "
        "minutes. Confirmed personal-data breaches are notified to the "
        "controller within 24 hours, and a written post-incident review is "
        "published within five working days.\n"
        "\n"
        "4. Vulnerability Management\n"
        "Critical vulnerabilities are patched within 7 days of disclosure, high "
        "within 30 days, and medium within 90 days. Dependency scanning runs on "
        "every pull request and blocks merge on a critical finding.",
    ),
]

QUESTIONS: list[GoldenQuestion] = [
    GoldenQuestion(
        "What invoice number was first issued under the new billing system?",
        ["billing"],
        "keyword",
        "INV-2291",
    ),
    GoldenQuestion(
        "How much paid time off do new parents get?",
        ["parental_leave"],
        "paraphrase",
        "16 weeks of fully paid leave, which can be split into two blocks within the first year.",
    ),
    GoldenQuestion(
        "Which CVE was fixed in the March security release?",
        ["security_patch"],
        "keyword",
        "CVE-2024-9981, a critical-severity vulnerability allowing unauthenticated access to internal admin routes.",
    ),
    GoldenQuestion(
        "What was the revenue figure last quarter and how did it change?",
        ["finance_q3"],
        "paraphrase",
        "$1.2 million, up 18% from the prior quarter, with gross margin holding steady at 62%.",
    ),
    GoldenQuestion(
        "What should a new employee finish during their first few days?",
        ["onboarding"],
        "paraphrase",
        "Laptop setup, badge activation, and the benefits enrollment form, within the first three days.",
    ),
    GoldenQuestion(
        "What port does the WireGuard VPN listen on?",
        ["vpn_setup"],
        "keyword",
        "Port 51820.",
    ),
    GoldenQuestion(
        "What's the daily cap for meals while traveling for work?",
        ["expense_policy"],
        "paraphrase",
        "$75 per day, with receipts required for any single expense over $25.",
    ),
    GoldenQuestion(
        "How long did incident INC-4471 last?",
        ["incident_4471"],
        "keyword",
        "47 minutes, caused by a misconfigured connection pool limit after a routine deploy.",
    ),
    GoldenQuestion(
        "How often does the company formally evaluate employee performance?",
        ["perf_review"],
        "paraphrase",
        "Twice a year, in April and October.",
    ),
    GoldenQuestion(
        "What's the per-minute request limit for an API key?",
        ["api_ratelimit"],
        "keyword",
        "1000 requests per minute; requests beyond that get an HTTP 429 with a Retry-After header.",
    ),
    GoldenQuestion(
        "How long are application logs kept before they're deleted?",
        ["data_retention"],
        "paraphrase",
        "90 days for application logs; audit logs covering account access are kept for 3 years.",
    ),
    GoldenQuestion(
        "What travel class should be used for short flights?",
        ["travel_policy"],
        "paraphrase",
        "Economy class, for flights under six hours.",
    ),
    GoldenQuestion(
        "How often do employees get a new company laptop?",
        ["equipment_policy"],
        "paraphrase",
        "Every three years, though an earlier replacement can be requested if IT confirms a hardware failure.",
    ),
    GoldenQuestion(
        "What's the referral bonus amount and when is it paid out?",
        ["referral_bonus"],
        "keyword",
        "$2,000, paid after the referred hire completes 90 days of employment.",
    ),
    GoldenQuestion(
        "How long does a primary on-call shift last?",
        ["oncall_rotation"],
        "paraphrase",
        "One full week, with a backup engineer assigned each rotation.",
    ),
    # Multi-relevant: exercises Recall@k/NDCG on questions with more than one
    # correct source rather than just precision on a single hit.
    GoldenQuestion(
        "Which policies mention a specific dollar amount?",
        ["expense_policy", "referral_bonus", "finance_q3"],
        "paraphrase",
        "The expense policy ($75/day meal cap), the referral bonus ($2,000), and Q3 revenue ($1.2 million).",
    ),
    GoldenQuestion(
        "Which documents reference a specific incident or vulnerability ID?",
        ["incident_4471", "security_patch"],
        "keyword",
        "Incident INC-4471 and CVE-2024-9981.",
    ),
    # --- chunking-sensitive -------------------------------------------------
    # Each of these targets a fact sitting in the middle of a long document,
    # several sections in. A flat splitter can strand that fact in a chunk with
    # no indication of which clause it belongs to; structure-aware chunking
    # keeps the heading attached. These are the questions that move when
    # chunking changes — the single-chunk fixtures above cannot.
    GoldenQuestion(
        "What interest rate applies to late payments?",
        ["msa_contract"],
        "paraphrase",
        "1.5% per month, or the maximum permitted by law if that is lower.",
    ),
    GoldenQuestion(
        "How are service level credits calculated and capped?",
        ["msa_contract"],
        "paraphrase",
        "10% of monthly fees for each full percentage point below the 99.9% target, capped at 50% "
        "of the monthly fee in any single month, and claimable within 30 days.",
    ),
    GoldenQuestion(
        "How quickly must critical vulnerabilities be patched?",
        ["security_handbook"],
        "paraphrase",
        "Within 7 days of disclosure; high within 30 days and medium within 90 days.",
    ),
    GoldenQuestion(
        "How often are encryption keys rotated?",
        ["security_handbook"],
        "paraphrase",
        "Every 12 months, stored in a managed key service and never in source control.",
    ),
    GoldenQuestion(
        "What is the egress overage rate and what does the base fee include?",
        ["msa_contract"],
        "paraphrase",
        "$80 per terabyte beyond the 10TB per month included in the $4,500 base fee.",
    ),
]
