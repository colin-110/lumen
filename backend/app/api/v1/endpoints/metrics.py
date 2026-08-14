"""Prometheus scrape endpoint, optionally behind a bearer token.

A plain route rather than `app.mount("/metrics", make_asgi_app())`. Mounting
a sub-application makes Starlette redirect `/metrics` to `/metrics/` with a
307 — and because the backend has no idea it is behind TLS, that redirect
points at `http://`. Through this project's Caddy front end, whose matcher is
`handle /metrics`, the redirected `/metrics/` then falls through to the
frontend instead of the API, so scraping the deployed instance never worked.

Being a normal route also means the token guard is an ordinary dependency
instead of a hand-rolled ASGI wrapper sitting in front of a mount.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings

router = APIRouter()


async def verify_metrics_token(request: Request) -> None:
    """Guard the scrape endpoint when METRICS_TOKEN is configured.

    Left open the endpoint publishes request volumes, latency distributions
    and error rates to anyone who asks. Unset is allowed because on a private
    network it is reasonable; outside `local` it raises a startup warning.
    """
    token = settings.METRICS_TOKEN
    if not token:
        return

    provided = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    # compare_digest, not ==: string comparison short-circuits on the first
    # differing byte, which leaks the token a character at a time.
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized to read metrics",
            headers={"WWW-Authenticate": 'Bearer realm="metrics"'},
        )


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(verify_metrics_token)])
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
