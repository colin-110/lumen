"""Ingestion tasks must share one event loop per worker process.

The bug this locks down: `process_document` used `asyncio.run()`, which closes
its loop on exit. The SQLAlchemy async engine is a module-level singleton, so
the asyncpg connections it pools stayed bound to the loop that opened them.
The first task in a worker process succeeded; every later one checked out a
connection belonging to a dead loop and failed with "got Future ... attached to
a different loop", retried, failed again, and left the document stuck in QUEUED.

A single-document smoke test passes either way, which is exactly why this
needs a test rather than a manual check.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import celery_app as celery_module
from app.core.celery_app import run_async


@pytest.fixture(autouse=True)
def _fresh_loop():
    """Don't let a test leak its loop into the next one, or into pytest-asyncio."""
    previous = celery_module._loop
    celery_module._loop = None
    yield
    if celery_module._loop is not None and not celery_module._loop.is_closed():
        celery_module._loop.close()
    celery_module._loop = previous


async def _running_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


def test_consecutive_calls_share_one_loop():
    first = run_async(_running_loop())
    second = run_async(_running_loop())
    third = run_async(_running_loop())
    assert first is second is third


def test_loop_is_left_open_between_calls():
    loop = run_async(_running_loop())
    assert not loop.is_closed(), "closing the loop is what orphaned the connection pool"


def test_loop_bound_resource_survives_into_the_next_task():
    """The actual failure, reduced.

    A Future is bound to the loop that created it — the same property that
    makes an asyncpg connection unusable from a different loop. Under
    `asyncio.run()` the second call raises "got Future attached to a different
    loop"; the whole point of run_async is that it does not.
    """

    async def make_future() -> asyncio.Future:
        return asyncio.get_running_loop().create_future()

    future = run_async(make_future())  # created during "task 1"

    async def resolve() -> int:
        future.set_result(7)
        return await future

    assert run_async(resolve()) == 7  # awaited during "task 2"


def test_a_closed_loop_is_replaced_rather_than_reused():
    """Belt and braces: if anything else in the process closes the loop, the
    next task should build a new one instead of raising RuntimeError."""
    loop = run_async(_running_loop())
    loop.close()
    replacement = run_async(_running_loop())
    assert replacement is not loop
    assert not replacement.is_closed()


def test_exceptions_propagate_and_leave_the_loop_usable():
    async def boom() -> None:
        raise ValueError("task failed")

    with pytest.raises(ValueError, match="task failed"):
        run_async(boom())

    # Celery retries the task in the same process, so a failure must not
    # poison the loop for the retry.
    assert run_async(_running_loop()) is celery_module._loop
