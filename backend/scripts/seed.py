"""Seed the default organization, admin account and optional demo account.

Run with: `python -m scripts.seed` from `backend/`, or via `make seed`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

import app.db.base  # noqa: F401 - registers every model so relationship() string refs resolve
from app.core.config import settings
from app.crud.crud_organization import organization as crud_organization
from app.crud.crud_user import user as crud_user
from app.db.session import AsyncSessionLocal
from app.schemas.user import UserCreate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _ensure_user(db, *, email: str, password: str, full_name: str, org_id) -> None:
    if await crud_user.get_by_email(db, email=email):
        logger.info("%s already exists. Skipping.", email)
        return
    user = await crud_user.create(
        db,
        obj_in=UserCreate(email=email, password=password, full_name=full_name),
        organization_id=org_id,
    )
    # Both seeded accounts get the retrieval debugger. Superuser grants nothing
    # else in this codebase (see deps.get_current_active_superuser), and the
    # debugger is scoped to the caller's own organization.
    user.is_superuser = True
    db.add(user)
    await db.commit()
    logger.info("Created %s", email)


async def seed() -> None:
    """Create the organization, the admin, and (if configured) a demo account.

    Idempotent: re-running it creates only what is missing. The demo account
    shares the admin's organization, so it can search documents the admin
    uploads, but it cannot delete them (deletion is owner-only). Its password
    is meant to be published on the login page, so never reuse it elsewhere.
    """
    logger.info("Starting database seed...")
    async with AsyncSessionLocal() as db:
        # get_or_create, so re-running the seed against a database that
        # already has the organization reuses it instead of tripping the
        # unique constraint on organization.name.
        org = await crud_organization.get_or_create_by_name(db, name=settings.FIRST_ORG_NAME)
        logger.info("Using organization: %s (%s)", org.name, org.id)

        await _ensure_user(
            db,
            email=settings.FIRST_SUPERUSER_EMAIL,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            full_name="Admin User",
            org_id=org.id,
        )
        if settings.DEMO_USER_EMAIL and settings.DEMO_USER_PASSWORD:
            await _ensure_user(
                db,
                email=settings.DEMO_USER_EMAIL,
                password=settings.DEMO_USER_PASSWORD,
                full_name="Demo User",
                org_id=org.id,
            )
        # Passwords are not logged: they come from the environment, so whoever
        # ran the seed already has them, and logs end up in less private places.

    if settings.SEED_DEMO_DOCUMENTS:
        await upload_demo_documents()


DEMO_DOCUMENTS_DIR = Path(__file__).parent / "demo_documents"


async def upload_demo_documents() -> None:
    """Upload the sample documents as the admin, through the running API.

    Going through the API rather than calling the ingestion code here keeps
    one copy of the embedding models in memory (the API's) and reuses its
    one-at-a-time ingestion queue. Re-running is safe: identical bytes are
    recognised as duplicates and not ingested again. Admin ownership means the
    shared demo account can search them but cannot delete them.
    """
    files = sorted(DEMO_DOCUMENTS_DIR.glob("*.txt"))
    api = settings.SEED_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            res = await client.post(
                f"{api}/auth/login",
                data={
                    "username": settings.FIRST_SUPERUSER_EMAIL,
                    "password": settings.FIRST_SUPERUSER_PASSWORD,
                },
            )
            res.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Skipping demo documents: could not sign in at %s (%s)", api, exc)
            return
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        for path in files:
            res = await client.post(
                f"{api}/documents/upload",
                headers=headers,
                files={"file": (path.name, path.read_bytes(), "text/plain")},
            )
            if res.status_code == 200:
                logger.info("Demo document %s already present", path.name)
            elif res.status_code == 201:
                logger.info("Uploaded demo document %s; it is being indexed", path.name)
            else:
                logger.warning(
                    "Demo document %s: HTTP %s %s", path.name, res.status_code, res.text[:200]
                )


if __name__ == "__main__":
    asyncio.run(seed())
