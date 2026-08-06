from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.crud.crud_conversation import conversation as crud_conversation
from app.db.session import get_db
from app.models.conversation import MessageRole
from app.models.user import User
from app.schemas.conversation import ChatRequest, ChatResponse, ChatSource
from app.services import agent as agent_service

router = APIRouter()


async def _get_or_create_conversation(db: AsyncSession, user: User, conversation_id: uuid.UUID | None):
    if conversation_id:
        convo = await crud_conversation.get_for_user(db, id=conversation_id, user_id=user.id)
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo
    return await crud_conversation.create(db, user_id=user.id)


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Non-streaming chat completion. Prefer `/chat/stream` for interactive UIs."""
    await enforce_rate_limit(f"chat:{current_user.id}", settings.RATE_LIMIT_CHAT_PER_MINUTE)

    convo = await _get_or_create_conversation(db, current_user, request.conversation_id)
    history_rows = (
        await crud_conversation.get_for_user(db, id=convo.id, user_id=current_user.id, with_messages=True)
    ).messages
    history = [agent_service.ChatMessage(role=m.role.value, content=m.content) for m in history_rows]

    await crud_conversation.add_message(db, convo.id, MessageRole.USER, request.message)
    await crud_conversation.rename_if_default(db, convo, request.message)

    sources: list[dict] = []
    text_parts: list[str] = []
    cached = False
    latency_ms = 0

    doc_ids = [str(d) for d in request.document_ids] if request.document_ids else None

    async for event in agent_service.run(
        request.message, history, current_user.organization_id, current_user.id, doc_ids
    ):
        if event.type == "sources":
            sources = event.data
        elif event.type == "token":
            text_parts.append(event.data)
        elif event.type == "done":
            cached = event.data.get("cached", False)
            latency_ms = event.data.get("latency_ms", 0)

    full_text = "".join(text_parts)
    await crud_conversation.add_message(
        db, convo.id, MessageRole.ASSISTANT, full_text, sources=sources, latency_ms=latency_ms, cached=cached
    )

    return ChatResponse(
        conversation_id=convo.id,
        message=full_text,
        sources=[ChatSource(**s) for s in sources],
        cached=cached,
        latency_ms=latency_ms,
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> StreamingResponse:
    """Token-level SSE stream. Frame format: `data: {"type": ..., "data": ...}\\n\\n`."""
    await enforce_rate_limit(f"chat:{current_user.id}", settings.RATE_LIMIT_CHAT_PER_MINUTE)

    convo = await _get_or_create_conversation(db, current_user, request.conversation_id)
    history_rows = (
        await crud_conversation.get_for_user(db, id=convo.id, user_id=current_user.id, with_messages=True)
    ).messages
    history = [agent_service.ChatMessage(role=m.role.value, content=m.content) for m in history_rows]

    await crud_conversation.add_message(db, convo.id, MessageRole.USER, request.message)
    await crud_conversation.rename_if_default(db, convo, request.message)

    doc_ids = [str(d) for d in request.document_ids] if request.document_ids else None

    async def event_generator():
        def frame(event_type: str, data: Any) -> str:
            return f"data: {json.dumps({'type': event_type, 'data': data}, default=str)}\n\n"

        yield frame("conversation", {"conversation_id": str(convo.id)})

        sources: list[dict] = []
        text_parts: list[str] = []
        cached = False
        latency_ms = 0

        try:
            async for event in agent_service.run(
                request.message, history, current_user.organization_id, current_user.id, doc_ids
            ):
                if event.type == "sources":
                    sources = event.data
                    yield frame("sources", sources)
                elif event.type == "token":
                    text_parts.append(event.data)
                    yield frame("token", event.data)
                elif event.type == "done":
                    cached = event.data.get("cached", False)
                    latency_ms = event.data.get("latency_ms", 0)
                elif event.type == "error":
                    yield frame("error", event.data)
        finally:
            full_text = "".join(text_parts)
            if full_text:
                # Persist even if the client disconnected mid-stream so the
                # conversation history stays consistent on next load.
                await crud_conversation.add_message(
                    db,
                    convo.id,
                    MessageRole.ASSISTANT,
                    full_text,
                    sources=sources,
                    latency_ms=latency_ms,
                    cached=cached,
                )

        yield frame("done", {"cached": cached, "latency_ms": latency_ms})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
