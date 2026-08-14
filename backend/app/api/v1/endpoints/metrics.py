"""Prometheus scrape endpoint, optionally behind a bearer token.

`make_asgi_app()` is mounted directly on the app, so it bypasses FastAPI's
dependency system entirely — an ordinary `Depends(...)` cannot protect it.
Left open it publishes request volumes, latency distributions and error rates
to anyone who asks, which is both an information leak and (combined with the
per-path metric labels) a way to make the process allocate.

The guard is a plain ASGI wrapper for the same reason: it has to sit in front
of the mounted sub-application rather than inside the router.
"""

from __future__ import annotations

import hmac

from prometheus_client import make_asgi_app
from starlette.types import Receive, Scope, Send

from app.core.config import settings

_prometheus_app = make_asgi_app()


async def _unauthorized(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"www-authenticate", b'Bearer realm="metrics"'),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"Unauthorized"})


async def metrics_app(scope: Scope, receive: Receive, send: Send) -> None:
    token = settings.METRICS_TOKEN
    if token:
        headers = dict(scope.get("headers") or [])
        provided = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {token}"
        # compare_digest, not ==: string comparison short-circuits on the
        # first differing byte, which leaks the token a character at a time.
        if not hmac.compare_digest(provided, expected):
            await _unauthorized(send)
            return
    await _prometheus_app(scope, receive, send)
