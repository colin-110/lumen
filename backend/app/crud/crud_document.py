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

    @staticmethod
    def _tenant_clause(owner_id: uuid.UUID, organization_id: uuid.UUID | None):
        """The same boundary `retrieval._tenant_filter` applies in Qdrant.

        These two had drifted apart: chat retrieved across the whole
        organization while the documents API was scoped to the owner, so an
        answer could cite — including a 600-character snippet of — a document
        the same user got a 404 for. Whatever the boundary is, both halves
        have to agree on it, so this is the single definition of it in
        Postgres and it mirrors the Qdrant one exactly.
        """
        if organization_id is not None:
            return Document.organization_id == organization_id
        return Document.owner_id == owner_id

    async def get_for_tenant(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        owner_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> Document | None:
        result = await db.execute(
            select(Document).where(
                Document.id == id, self._tenant_clause(owner_id, organization_id)
            )
        )
        return result.scalars().first()

    async def get_multi_for_tenant(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Document]:
        result = await db.execute(
            select(Document)
            .where(self._tenant_clause(owner_id, organization_id))
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_tenant(
        self, db: AsyncSession, owner_id: uuid.UUID, organization_id: uuid.UUID | None
    ) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(Document)
            .where(self._tenant_clause(owner_id, organization_id))
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
