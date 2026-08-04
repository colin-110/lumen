from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


class CRUDUser:
    async def get(self, db: AsyncSession, id: uuid.UUID | str) -> User | None:
        result = await db.execute(select(User).where(User.id == id))
        return result.scalars().first()

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def create(
        self, db: AsyncSession, obj_in: UserCreate, organization_id: uuid.UUID | None
    ) -> User:
        db_obj = User(
            email=obj_in.email,
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name,
            organization_id=organization_id,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(self, db: AsyncSession, db_obj: User, obj_in: UserUpdate) -> User:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "password" in update_data:
            password = update_data.pop("password")
            if password:
                db_obj.hashed_password = get_password_hash(password)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def authenticate(self, db: AsyncSession, email: str, password: str) -> User | None:
        user = await self.get_by_email(db, email=email)
        if not user:
            # Run the hash comparison anyway to keep timing similar whether
            # or not the account exists (mitigates user-enumeration timing).
            get_password_hash(password)
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def is_active(self, user: User) -> bool:
        return user.is_active

    def is_superuser(self, user: User) -> bool:
        return user.is_superuser


user = CRUDUser()
