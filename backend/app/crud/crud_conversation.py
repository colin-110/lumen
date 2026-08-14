from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, Message, MessageRole


class CRUDConversation:
    async def get_for_user(
        self, db: AsyncSession, id: uuid.UUID, user_id: uuid.UUID, with_messages: bool = False
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == id, Conversation.user_id == user_id)
        if with_messages:
            stmt = stmt.options(selectinload(Conversation.messages))
        result = await db.execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self, db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> list[Conversation]:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str | None = None
    ) -> Conversation:
        db_obj = Conversation(user_id=user_id, title=title or "New conversation")
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def touch(self, db: AsyncSession, conversation_id: uuid.UUID) -> None:
        """Bump updated_at so the sidebar sorts most-recent-first.

        `list_for_user` orders by `Conversation.updated_at`, but adding a
        message only INSERTs into `message` — the conversation row is never
        written, so `onupdate=func.now()` never fires. Without this call the
        sidebar orders by when each conversation was *created*, and a chat you
        have been using all afternoon sinks to the bottom.

        Takes an id rather than an instance so it can be called from the SSE
        generator, which runs after the request's ORM objects are out of scope.
        """
        await db.execute(
            Conversation.__table__.update()
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await db.commit()

    async def rename_if_default(
        self, db: AsyncSession, conversation: Conversation, new_title: str
    ) -> None:
        if conversation.title == "New conversation":
            conversation.title = new_title[:255]
            db.add(conversation)
            await db.commit()

    async def add_message(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        sources: list | None = None,
        latency_ms: int | None = None,
        cached: bool = False,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources or [],
            latency_ms=latency_ms,
            cached=cached,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    async def remove(self, db: AsyncSession, conversation: Conversation) -> None:
        await db.delete(conversation)
        await db.commit()


conversation = CRUDConversation()
