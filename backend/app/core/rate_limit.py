"""Fixed-window rate limiting backed by Redis.

Deliberately simple (INCR + EXPIRE, not a sliding-window Lua script) — this
protects the LLM/embedding endpoints from accidental hammering, not from a
determined attacker. Good enough for that job at a fraction of the
complexity.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    return _redis


async def enforce_rate_limit(key: str, limit_per_minute: int) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    redis = get_redis()
    window = int(time.time() // 60)
    bucket_key = f"ratelimit:{key}:{window}"
    count = await redis.incr(bucket_key)
    if count == 1:
        await redis.expire(bucket_key, 60)
    if count > limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
        )
