"""A streaming answer that goes quiet must fail, not hang the request."""

from __future__ import annotations

import asyncio

import pytest

from app.services.agent import _idle_timeout


async def _chunks(*items, stall_after: int | None = None):
    for i, item in enumerate(items):
        if stall_after is not None and i == stall_after:
            await asyncio.sleep(3600)
        yield item


async def test_a_healthy_stream_passes_through_unchanged():
    out = [c async for c in _idle_timeout(_chunks("a", "b", "c"), seconds=1)]
    assert out == ["a", "b", "c"]


async def test_a_stream_that_stalls_before_any_output_raises():
    with pytest.raises(TimeoutError, match="stalled"):
        async for _ in _idle_timeout(_chunks("a", stall_after=0), seconds=0.05):
            pass


async def test_a_stream_that_stalls_midway_raises_after_the_delivered_chunks():
    received = []
    with pytest.raises(TimeoutError):
        async for chunk in _idle_timeout(_chunks("a", "b", "c", stall_after=2), seconds=0.05):
            received.append(chunk)
    assert received == ["a", "b"]
