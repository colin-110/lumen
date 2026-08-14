"""Shared fixtures.

Integration tests here talk to a real Postgres (and, where relevant, Redis)
because the bugs worth catching in this codebase live in the seams that unit
tests cannot reach: dependency lifetimes, transaction boundaries, the SSE
response body, and the interaction between SQLAlchemy relationships and
`updated_at`. Every one of those looked correct in isolation.

They are skipped — not failed — when no database is reachable, so
`pytest` on a laptop with nothing running still executes the unit suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import AsyncGenerator

import pytest

# Must be set before app.core.config is imported anywhere.
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SEMANTIC_CACHE_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


def _database_reachable() -> bool:
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    try:
        engine = create_engine(settings.SYNC_DATABASE_URI, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database() -> None:
    """Ensure the schema exists, or skip every test that depends on this."""
    if not _database_reachable():
        pytest.skip("no Postgres reachable; skipping integration tests", allow_module_level=False)

    from sqlalchemy import create_engine

    import app.db.base  # noqa: F401 - registers every model
    from app.core.config import settings
    from app.db.base_class import Base

    engine = create_engine(settings.SYNC_DATABASE_URI)
    Base.metadata.create_all(engine, checkfirst=True)
    engine.dispose()


@pytest.fixture
async def db_session(database) -> AsyncGenerator:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def clean_tables(database) -> AsyncGenerator[None, None]:
    """Truncate between tests so ordering never matters."""
    from sqlalchemy import text

    from app.db.session import engine

    async def _truncate() -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    'TRUNCATE "message", "conversation", "document", "user", "organization" CASCADE'
                )
            )

    await _truncate()
    yield
    await _truncate()


@pytest.fixture
async def client(clean_tables) -> AsyncGenerator:
    """An httpx client bound to the real ASGI app.

    The app's lifespan is deliberately not run: it would reach for Qdrant,
    MinIO and the ONNX models, none of which these tests need. Anything that
    would touch them is stubbed per-test instead.
    """
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def unique_email() -> str:
    # example.com, not example.test: `email-validator` rejects special-use and
    # reserved TLDs, so a .test address fails schema validation before it ever
    # reaches the code under test.
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


async def register_and_login(client, email: str, password: str = "correct-horse-battery", **extra):
    """Create an account and return (user_json, auth_headers)."""
    payload = {"email": email, "password": password, **extra}
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201, res.text
    user = res.json()

    res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    tokens = res.json()
    return user, {"Authorization": f"Bearer {tokens['access_token']}"}


@contextlib.asynccontextmanager
async def _noop():  # pragma: no cover - helper kept for symmetry
    yield


__all__ = ["register_and_login", "asyncio"]
