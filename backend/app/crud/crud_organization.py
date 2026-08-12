from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


class CRUDOrganization:
    async def get(self, db: AsyncSession, id: uuid.UUID) -> Organization | None:
        result = await db.execute(select(Organization).where(Organization.id == id))
        return result.scalars().first()

    async def get_by_name(self, db: AsyncSession, name: str) -> Organization | None:
        # Case-insensitive: "Acme Corp" and "acme corp" are the same company to
        # everyone except a byte comparison, and putting them in separate
        # tenants is exactly the bug this lookup exists to prevent.
        result = await db.execute(
            select(Organization).where(func.lower(Organization.name) == name.strip().lower())
        )
        return result.scalars().first()

    async def get_or_create_by_name(self, db: AsyncSession, name: str) -> Organization:
        name = name.strip()
        existing = await self.get_by_name(db, name=name)
        if existing:
            return existing

        org = Organization(name=name)
        db.add(org)
        try:
            await db.commit()
        except IntegrityError:
            # Two registrations for the same new organization raced; the
            # unique index picked a winner, so use it.
            await db.rollback()
            winner = await self.get_by_name(db, name=name)
            if winner is None:  # pragma: no cover - only if the row vanished
                raise
            return winner
        await db.refresh(org)
        return org


organization = CRUDOrganization()
