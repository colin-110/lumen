"""Seed a default organization + superuser for local development.

Run with: `python -m scripts.seed` from `backend/`, or via `make seed`.
"""

from __future__ import annotations

import asyncio
import logging

import app.db.base  # noqa: F401 - registers every model so relationship() string refs resolve
from app.core.config import settings
from app.crud.crud_user import user as crud_user
from app.db.session import AsyncSessionLocal
from app.models.organization import Organization
from app.schemas.user import UserCreate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed() -> None:
    logger.info("Starting database seed...")
    async with AsyncSessionLocal() as db:
        existing = await crud_user.get_by_email(db, email=settings.FIRST_SUPERUSER_EMAIL)
        if existing:
            logger.info("Superuser %s already exists. Skipping seed.", settings.FIRST_SUPERUSER_EMAIL)
            return

        org = Organization(name=settings.FIRST_ORG_NAME)
        db.add(org)
        await db.commit()
        await db.refresh(org)
        logger.info("Created organization: %s (%s)", org.name, org.id)

        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER_EMAIL,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            full_name="Admin User",
        )
        user = await crud_user.create(db, obj_in=user_in, organization_id=org.id)
        user.is_superuser = True
        db.add(user)
        await db.commit()
        logger.info("Created superuser: %s", user.email)
        logger.info("Login with email=%s password=%s", settings.FIRST_SUPERUSER_EMAIL, settings.FIRST_SUPERUSER_PASSWORD)


if __name__ == "__main__":
    asyncio.run(seed())
