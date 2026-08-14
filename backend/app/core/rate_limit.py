"""Fixed-window rate limiting backed by Redis.

Deliberately simple (INCR + EXPIRE, not a sliding-window Lua script) — this
protects the LLM/embedding endpoints from accidental hammering, not from a
determined attacker. Good enough for that job at a fraction of the
complexity.

Fails *open*: if Redis is unreachable the request is allowed and the failure
is logged. A limiter whose own dependency going down takes out chat and
uploads is a worse outage than the one it prevents — and Redis is already a
soft dependency everywhere else here (the semantic cache degrades to a miss
rather than an error).
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            str(settings.REDIS_URL),
            decode_responses=True,
            # Without these a Redis that accepts the connection but never
            # answers hangs the request for as long as the client waits.
            socket_timeout=2,
            socket_connect_timeout=2,
        )
    return _redis


async def enforce_rate_limit(key: str, limit_per_minute: int) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return

    window = int(time.time() // 60)
    bucket_key = f"ratelimit:{key}:{window}"

    try:
        redis = get_redis()
        count = await redis.incr(bucket_key)
        if count == 1:
            await redis.expire(bucket_key, 60)
    except (RedisError, OSError):
        logger.warning("Rate limiter unavailable; allowing request for %s", key, exc_info=True)
        return

    if count > limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": "60"},
        )


def client_ip(request: Request) -> str:
    """Best-effort client address for limiting unauthenticated endpoints.

    `X-Forwarded-For` is trusted only when TRUSTED_PROXY_HEADERS is on,
    because the header is client-supplied: honouring it unconditionally lets
    an attacker rotate a fake value per request and bypass the limit
    entirely. Behind a reverse proxy the flag is correct, and without it the
    socket address is the proxy's — collapsing every user into a single
    bucket, so one person hitting the limit locks out everybody.

    The *rightmost* entry is used, not the leftmost. Proxies append: a
    request arriving with a forged `X-Forwarded-For: 1.2.3.4` comes out of
    Caddy as `1.2.3.4, <real client>`, so reading the left end reads the
    attacker's own value and hands them an unlimited supply of buckets. The
    last entry is the one the trusted proxy wrote itself.

    This assumes exactly one trusted proxy in front, which is what this
    project deploys (Caddy). Behind a chain, this needs to count hops.
    """
    if settings.TRUSTED_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if hops:
                return hops[-1][:64]
    return request.client.host if request.client else "unknown"
