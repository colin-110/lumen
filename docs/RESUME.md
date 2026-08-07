# Lumen — resume and interview material

Everything here is a number this repo actually produced. Each row names the command that
regenerates it, because the only thing worse than no metric in an interview is one you
can't reproduce when asked.

- **Live:** https://3-218-31-157.nip.io
- **Repo:** https://github.com/colin-110/lumen
- **Demo login:** `admin@enterprise.ai`

---

## The header line

> **Lumen — self-hosted RAG document assistant** · Python, FastAPI, Next.js, Qdrant, Celery, Docker, AWS
> github.com/colin-110/lumen · live at 3-218-31-157.nip.io

---

## Bullets

Pick three or four. They are ordered by how well they survive follow-up questions.

**Retrieval quality, measured rather than asserted**
> Built a golden-dataset evaluation harness (Recall@k, MRR, NDCG@k) that runs the production
> retrieval code paths, and used it to compare four strategies; hybrid dense+sparse retrieval
> with cross-encoder reranking reached **100% Recall@5 vs 94% for BM25 alone**, at a measured
> 266ms vs 18ms — making the accuracy/latency trade-off explicit instead of assumed.

**The bug that load testing found**
> Load testing surfaced that the semantic cache had **never worked**: an upstream client library
> removed the method it called, the resulting `AttributeError` was swallowed by correct-looking
> error handling, and every lookup returned a clean miss. Fixing it cut repeat-question latency
> from **15,411 ms to 44 ms (350×)**. No test failed and no log line was alarming — only
> measurement found it.

**Concurrency bug in the ingestion worker**
> Diagnosed an ingestion outage where only the first document per worker process was ever
> indexed: Celery ran each task under `asyncio.run()`, which closed the loop that the shared
> SQLAlchemy connection pool was bound to, so every later task failed with "got Future attached
> to a different loop" and left documents stuck in `QUEUED`. Fixed with one long-lived event
> loop per worker process, and locked it down with a regression test — a single-document smoke
> test passes either way, which is why it survived manual testing.

**Efficiency work, with before/after numbers**
> Cut the running stack from **1,730 MiB to 850 MiB** across nine containers and the backend
> image from **1.67 GB to 1.41 GB**, and reduced cold-start import time **11.4 s → 3.1 s** by
> moving a 340 MB LLM-routing dependency off the module-scope import path — enough to run the
> whole system on a 1 GB AWS free-tier instance.

**Capacity limits, found not guessed**
> Load tested the deployed stack end to end: **401 req/s** at concurrency 5, a reproducible
> **container OOM kill at concurrency 50**, and retrieval p95 degrading **1.4 s → 22 s** from
> concurrency 1 to 5 — identifying CPU-bound cross-encoder reranking as the scaling bottleneck
> and a shared embedding service as the fix.

**Multi-tenant correctness**
> Wrote a security test suite asserting that every vector-search entry point carries a tenant
> filter and that caller-supplied `document_ids` (attacker-controlled, it arrives in the request
> body) is ANDed onto that filter rather than replacing it — cross-tenant leakage here would be
> silent, since a wrong answer still reads as a plausible one.

**Shipping**
> Deployed to AWS EC2 behind Caddy with automatic TLS, with CI/CD on every push to `main`:
> lint → 126 tests → build → deploy over **AWS SSM rather than SSH**, so the instance needs no
> inbound port open to GitHub's runner IP ranges, and the deploy IAM user is scoped to
> `ssm:SendCommand` on a single instance ARN.

---

## Verified numbers

| Claim | Value | How to reproduce |
|---|---|---|
| Tests | 126 (100 pytest, 26 vitest) | `make test` |
| Recall@5, hybrid + rerank | 100% | `make eval-retrieval` |
| Recall@5, BM25 only | 94% | `make eval-retrieval` |
| Semantic cache hit | 44 ms (vs 15,411 ms miss) | `python backend/scripts/load_test.py` |
| Throughput, `/health` @ c5 | 401 req/s | `python backend/scripts/load_test.py` (run outside the container) |
| Failure point | OOM kill at c50 (exit 137) | `python backend/scripts/load_test.py` |
| Retrieval p95, c1 → c5 | 1,417 ms → 22,218 ms | `python backend/scripts/load_test.py` |
| Stack memory | 1,730 → 850 MiB | `docker stats` |
| Backend image | 1.67 → 1.41 GB | `docker images` |
| Cold import | 11.4 → 3.1 s | `python -X importtime -c "import app.main"` |

Two honest caveats to volunteer before you're asked:

- The golden-dataset corpus is small and topically distinct, so every strategy scores well;
  the gap between strategies widens on noisier real corpora. Say this first — it's the obvious
  follow-up question, and having the answer ready is worth more than the metric.
- Generation-quality numbers (faithfulness via LLM-as-judge) are implemented but not published,
  because the runs available were quota-limited. An earlier draft measured 0.40 faithfulness,
  which turned out to be a truncated-JSON parser bug in the judge, not a property of the system.
  Publishing that number would have been worse than publishing none.

---

## Interview talking points

**"Why not LangChain?"**
Every layer it would have provided — chunking, retrieval, prompt assembly, provider fallback —
is a layer whose behaviour needed to be measurable. The context-truncation bug (the prompt was
built from a 600-character UI preview while chunks are 1000 characters, so the model was blind
to 40% of every chunk) was found by reading the assembled prompt. That's harder to do through a
framework abstraction, and the abstraction wasn't buying much: the pipeline is ~200 lines.

**"How do you know retrieval works?"**
There's a golden dataset with ground-truth chunk labels and a harness that scores four retrieval
strategies against it through the production code paths. It runs without an LLM, so it costs
nothing and can run in CI. That's also how the reranker earned its 266 ms.

**"What's the scaling bottleneck?"**
Cross-encoder reranking. It's CPU-bound and in-process, so at concurrency 5 requests queue behind
each other and p95 goes from 1.4 s to 22 s. The fix is to move embedding and reranking to a
separate service that can scale independently of the API — not more API replicas, since each
replica loads its own ~500 MB copy of the ONNX weights, which is also what causes the OOM at
concurrency 50.

**"Tell me about a bug that was hard to find."**
Two good ones, both invisible to code review:
- The semantic cache that never worked (correct error handling hiding a permanent failure).
- The Celery event-loop bug (worked perfectly for the first document in each worker process).
Both were found by measuring behaviour rather than reading code, and both now have regression
tests that fail on the old implementation.

**"What would you do next?"**
A global spend cap — per-user rate limits don't bound total cost with open registration; a shared
embedding/rerank service, per the bottleneck above; and integration tests covering the full
upload → ingest → retrieve → answer path, which is currently the largest untested seam.
