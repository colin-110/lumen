from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate


class CRUDDocument:
    async def get(self, db: AsyncSession, id: uuid.UUID) -> Document | None:
        result = await db.execute(select(Document).where(Document.id == id))
        return result.scalars().first()

    async def get_for_owner(self, db: AsyncSession, id: uuid.UUID, owner_id: uuid.UUID) -> Document | None:
        result = await db.execute(
            select(Document).where(Document.id == id, Document.owner_id == owner_id)
        )
        return result.scalars().first()

    async def get_multi_by_owner(
        self, db: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Document]:
        result = await db.execute(
            select(Document)
            .where(Document.owner_id == owner_id)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_owner(self, db: AsyncSession, owner_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
        )
        return int(result.scalar_one())

    async def create(self, db: AsyncSession, obj_in: DocumentCreate) -> Document:
        data = obj_in.model_dump(exclude_none=True)
        db_obj = Document(**data)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(self, db: AsyncSession, db_obj: Document, obj_in: DocumentUpdate) -> Document:
        for field, value in obj_in.model_dump(exclude_unset=True).items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def remove(self, db: AsyncSession, db_obj: Document) -> None:
        await db.delete(db_obj)
        await db.commit()


document = CRUDDocument()
