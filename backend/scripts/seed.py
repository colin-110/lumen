"""Seed a default organization + superuser for local development.

Run with: `python -m scripts.seed` from `backend/`, or via `make seed`.
"""

from __future__ import annotations

import asyncio
import logging

import app.db.base  # noqa: F401 - registers every model so relationship() string refs resolve
from app.core.config import settings
from app.crud.crud_organization import organization as crud_organization
from app.crud.crud_user import user as crud_user
from app.db.session import AsyncSessionLocal
from app.schemas.user import UserCreate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed() -> None:
    logger.info("Starting database seed...")
    async with AsyncSessionLocal() as db:
        existing = await crud_user.get_by_email(db, email=settings.FIRST_SUPERUSER_EMAIL)
        if existing:
            logger.info(
                "Superuser %s already exists. Skipping seed.", settings.FIRST_SUPERUSER_EMAIL
            )
            return

        # get_or_create, so re-running the seed against a database that
        # already has the organization reuses it instead of tripping the
        # unique constraint on organization.name.
        org = await crud_organization.get_or_create_by_name(db, name=settings.FIRST_ORG_NAME)
        logger.info("Using organization: %s (%s)", org.name, org.id)

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
        # The password is not logged. It comes from FIRST_SUPERUSER_PASSWORD
        # in the environment, so whoever ran the seed already has it, and log
        # output routinely ends up somewhere less private than the .env file.
        logger.info("Sign in with the password from FIRST_SUPERUSER_PASSWORD.")


if __name__ == "__main__":
    asyncio.run(seed())
