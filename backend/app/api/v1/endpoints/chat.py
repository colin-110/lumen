from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.crud.crud_conversation import conversation as crud_conversation
from app.db.session import AsyncSessionLocal, get_db
from app.models.conversation import Conversation, MessageRole
from app.models.user import User
from app.schemas.conversation import ChatRequest, ChatResponse, ChatSource
from app.services import agent as agent_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Strong references to persistence writes that outlived their request, so the
# event loop can't garbage-collect a task mid-INSERT. Entries remove
# themselves on completion.
_detached_writes: set[asyncio.Task] = set()


async def _load_conversation(
    db: AsyncSession, user: User, conversation_id: uuid.UUID | None
) -> tuple[Conversation, list[agent_service.ChatMessage]]:
    """Resolve the conversation and its history in a single round trip.

    Previously this was two queries — one to fetch/create the conversation and
    a second, identical-but-for-`with_messages`, to read its history.
    """
    if conversation_id is None:
        return await crud_conversation.create(db, user_id=user.id), []

    convo = await crud_conversation.get_for_user(
        db, id=conversation_id, user_id=user.id, with_messages=True
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    history = [
        agent_service.ChatMessage(role=m.role.value, content=m.content) for m in convo.messages
    ]
    return convo, history


async def _persist_assistant_message(
    conversation_id: uuid.UUID,
    text: str,
    sources: list[dict],
    latency_ms: int,
    cached: bool,
) -> None:
    """Write the assistant turn using a session of its own.

    It cannot reuse the request's `Depends(get_db)` session. Since FastAPI
    0.106 the exit stack for yield-dependencies is closed *before* the
    response body is streamed; measured on fastapi 0.115.14 / starlette
    0.46.2 the order is: dependency enter -> endpoint -> **dependency exit**
    -> stream body.

    The failure that causes is quiet rather than loud. SQLAlchemy does not
    raise on a closed session — it checks out a fresh connection — so the
    INSERT succeeds and everything looks fine. But `get_db`'s `async with`
    has already run, so nothing ever returns that connection to the pool. It
    leaks until the garbage collector terminates it ("The garbage collector
    is trying to clean up non-checked-in connection..."), one per streamed
    chat, against a pool of 20 + 10 overflow.
    """
    try:
        async with AsyncSessionLocal() as db:
            await crud_conversation.add_message(
                db,
                conversation_id,
                MessageRole.ASSISTANT,
                text,
                sources=sources,
                latency_ms=latency_ms,
                cached=cached,
            )
            await crud_conversation.touch(db, conversation_id)
    except Exception:
        # Losing the transcript must not also break the stream the user is
        # still reading.
        logger.error("Failed to persist assistant message for %s", conversation_id, exc_info=True)


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Non-streaming chat completion. Prefer `/chat/stream` for interactive UIs."""
    await enforce_rate_limit(f"chat:{current_user.id}", settings.RATE_LIMIT_CHAT_PER_MINUTE)

    convo, history = await _load_conversation(db, current_user, request.conversation_id)

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
        db,
        convo.id,
        MessageRole.ASSISTANT,
        full_text,
        sources=sources,
        latency_ms=latency_ms,
        cached=cached,
    )
    await crud_conversation.touch(db, convo.id)

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

    convo, history = await _load_conversation(db, current_user, request.conversation_id)

    await crud_conversation.add_message(db, convo.id, MessageRole.USER, request.message)
    await crud_conversation.rename_if_default(db, convo, request.message)

    # Snapshot everything the generator needs. It must not close over `db` or
    # any ORM instance: both belong to a request scope that ends before the
    # body is streamed.
    conversation_id = convo.id
    organization_id = current_user.organization_id
    owner_id = current_user.id
    doc_ids = [str(d) for d in request.document_ids] if request.document_ids else None

    async def event_generator():
        def frame(event_type: str, data: Any) -> str:
            return f"data: {json.dumps({'type': event_type, 'data': data}, default=str)}\n\n"

        yield frame("conversation", {"conversation_id": str(conversation_id)})

        sources: list[dict] = []
        text_parts: list[str] = []
        cached = False
        latency_ms = 0

        try:
            async for event in agent_service.run(
                request.message, history, organization_id, owner_id, doc_ids
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
                # Persist even if the client disconnected mid-stream, so the
                # history stays consistent on next load.
                #
                # Awaiting directly here does not achieve that: a disconnect
                # cancels this task, and the first `await` in the cleanup path
                # re-raises CancelledError before the INSERT is issued — so the
                # case this exists for was exactly the case it failed. Running
                # it as a detached task and only *waiting* for it on the normal
                # path means the write survives the cancellation.
                write = asyncio.create_task(
                    _persist_assistant_message(
                        conversation_id, full_text, sources, latency_ms, cached
                    )
                )
                _detached_writes.add(write)
                write.add_done_callback(_detached_writes.discard)
                await asyncio.shield(write)

        yield frame("done", {"cached": cached, "latency_ms": latency_ms})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
