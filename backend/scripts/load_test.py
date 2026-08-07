"""Lightweight async load test against a running Lumen stack.

Not a replacement for a real tool (k6/locust) on a real target — this is
sized for a demo/portfolio README: enough concurrency to show real
throughput and percentile latency numbers without external dependencies
beyond httpx, and without hammering a rate-limited LLM API key.

Usage: python scripts/load_test.py  (backend must be running at :8000)
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time

import httpx

# Point at a deployment with:  python scripts/load_test.py https://host user pass
BASE = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("LOAD_TEST_BASE", "http://localhost:8000")).rstrip("/")
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "admin@enterprise.ai"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "admin12345"
API = f"{BASE}/api/v1"


def summarize(name: str, latencies_ms: list[float], wall_seconds: float, errors: int) -> None:
    n = len(latencies_ms)
    latencies_ms.sort()
    p50 = latencies_ms[int(n * 0.50)] if n else 0
    p95 = latencies_ms[int(n * 0.95) - 1] if n else 0
    p99 = latencies_ms[int(n * 0.99) - 1] if n else 0
    rps = n / wall_seconds if wall_seconds > 0 else 0
    print(f"\n== {name} ==")
    print(f"  requests: {n}  errors: {errors}  wall: {wall_seconds:.2f}s  throughput: {rps:.1f} req/s")
    print(f"  latency (ms)  min={min(latencies_ms):.1f}  mean={statistics.mean(latencies_ms):.1f}  "
          f"p50={p50:.1f}  p95={p95:.1f}  p99={p99:.1f}  max={max(latencies_ms):.1f}")


async def hit(client: httpx.AsyncClient, method: str, path: str, **kw) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        resp = await client.request(method, path, **kw)
        ok = resp.status_code < 400
    except Exception:
        ok = False
    return (time.perf_counter() - start) * 1000, ok


async def run_concurrent(client: httpx.AsyncClient, name: str, n: int, concurrency: int, method: str, path: str, **kw):
    sem = asyncio.Semaphore(concurrency)

    async def bound():
        async with sem:
            return await hit(client, method, path, **kw)

    start = time.perf_counter()
    results = await asyncio.gather(*(bound() for _ in range(n)))
    wall = time.perf_counter() - start
    latencies = [r[0] for r in results]
    errors = sum(1 for r in results if not r[1])
    summarize(name, latencies, wall, errors)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as anon:
        # 1. Raw framework throughput ceiling (no DB, no auth).
        await run_concurrent(anon, "GET /health (100 requests, concurrency 50)", 100, 50, "GET", "/health")

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # Log in once, reuse the token for every authenticated request below.
        login = await client.post(
            f"{API}/auth/login",
            data={"username": EMAIL, "password": PASSWORD},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        # 2. Authenticated, DB-backed read under load.
        await run_concurrent(
            client, "GET /api/v1/documents/ (200 requests, concurrency 20)", 200, 20, "GET", "/documents/"
        )

        # 3. Retrieval under concurrency. This is the interesting one for a RAG
        #    system: it exercises the dense + sparse embedding of the query and
        #    the cross-encoder rerank, all CPU-bound in-process, with no LLM
        #    call and therefore no provider quota consumed.
        await run_concurrent(
            client,
            "POST /debug/retrieval (60 requests, concurrency 10) - full hybrid+rerank",
            60, 10, "POST", f"{API}/debug/retrieval",
            json={"message": "What are the payment terms and the overage rate?"},
        )

        # 4. Semantic cache: same question asked twice back-to-back.
        #    First call is a real retrieval + LLM generation (cache miss);
        #    second should hit the Redis/Qdrant semantic cache.
        question = {"message": "What is Lumen and how does its retrieval pipeline work?"}
        t0 = time.perf_counter()
        r1 = await client.post(f"{API}/chat/", json=question)
        miss_ms = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        r2 = await client.post(f"{API}/chat/", json=question)
        hit_ms = (time.perf_counter() - t1) * 1000

        print("\n== Semantic cache impact (same question, back-to-back) ==")
        print(f"  cold (cache miss): {miss_ms:.0f}ms  status={r1.status_code}")
        print(f"  warm (cache hit):  {hit_ms:.0f}ms  status={r2.status_code}"
              f"  cached={r2.json().get('cached') if r2.status_code == 200 else 'n/a'}")
        if miss_ms > 0 and hit_ms > 0:
            print(f"  speedup: {miss_ms / hit_ms:.1f}x")


if __name__ == "__main__":
    asyncio.run(main())
