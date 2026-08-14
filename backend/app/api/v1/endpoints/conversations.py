from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.crud.crud_conversation import conversation as crud_conversation
from app.db.session import get_db
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead

router = APIRouter()


@router.get("/", response_model=list[ConversationRead])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return await crud_conversation.list_for_user(
        db, user_id=current_user.id, skip=skip, limit=limit
    )


@router.post("/", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return await crud_conversation.create(db, user_id=current_user.id, title=body.title)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    convo = await crud_conversation.get_for_user(
        db, id=conversation_id, user_id=current_user.id, with_messages=True
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    convo = await crud_conversation.get_for_user(db, id=conversation_id, user_id=current_user.id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await crud_conversation.remove(db, conversation=convo)
