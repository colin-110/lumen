"""The streaming chat path, end to end against a real database.

`/chat/stream` returns a StreamingResponse whose generator ran *after*
FastAPI had already closed the request's `Depends(get_db)` session — a
lifetime change FastAPI made in 0.106. Nothing in a unit test can see that:
the endpoint function returns successfully, and the defect only appears once
the response body is actually consumed.

The agent is stubbed. What is under test is persistence and ordering, not the
LLM.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


@pytest.fixture
def stub_agent(monkeypatch):
    """Replace the pipeline with a deterministic token stream."""
    from app.services import agent as agent_service

    def _make(tokens=("Hello", " there"), delay: float = 0.0):
        async def fake_run(query, history, organization_id, owner_id, document_ids=None):
            yield agent_service.PipelineEvent(
                "sources",
                [
                    {
                        "index": 1,
                        "filename": "handbook.pdf",
                        "document_id": "doc-1",
                        "chunk_id": "chunk-1",
                        "score": 1.0,
                        "snippet": "a snippet",
                    }
                ],
            )
            for token in tokens:
                if delay:
                    await asyncio.sleep(delay)
                yield agent_service.PipelineEvent("token", token)
            yield agent_service.PipelineEvent("done", {"cached": False, "latency_ms": 12})

        monkeypatch.setattr(agent_service, "run", fake_run)

    return _make


async def _read_stream(client, headers, message: str, conversation_id: str | None = None) -> str:
    body = {"message": message, "conversation_id": conversation_id}
    chunks: list[str] = []
    async with client.stream(
        "POST", "/api/v1/chat/stream", json=body, headers=headers
    ) as response:
        assert response.status_code == 200, await response.aread()
        async for piece in response.aiter_text():
            chunks.append(piece)
    return "".join(chunks)


class TestStreamingPersistence:
    async def test_assistant_reply_is_persisted_after_the_stream_completes(
        self, client, stub_agent, unique_email
    ):
        stub_agent(tokens=("Hello", " there"))
        _, headers = await register_and_login(client, unique_email)

        raw = await _read_stream(client, headers, "hi")
        assert "Hello" in raw and "[DONE]" in raw

        conversations = (await client.get("/api/v1/conversations/", headers=headers)).json()
        assert len(conversations) == 1

        detail = (
            await client.get(f"/api/v1/conversations/{conversations[0]['id']}", headers=headers)
        ).json()
        roles = [m["role"] for m in detail["messages"]]
        contents = [m["content"] for m in detail["messages"]]

        assert roles == ["user", "assistant"], "the assistant turn was never written"
        assert contents == ["hi", "Hello there"]
        assert detail["messages"][1]["sources"], "sources were dropped on the way to the database"

    async def test_history_is_replayed_into_the_next_turn(self, client, stub_agent, unique_email):
        stub_agent(tokens=("first",))
        _, headers = await register_and_login(client, unique_email)

        await _read_stream(client, headers, "one")
        conversation_id = (await client.get("/api/v1/conversations/", headers=headers)).json()[0]["id"]

        stub_agent(tokens=("second",))
        await _read_stream(client, headers, "two", conversation_id=conversation_id)

        detail = (
            await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
        ).json()
        assert [m["content"] for m in detail["messages"]] == ["one", "first", "two", "second"]

    async def test_a_conversation_cannot_be_hijacked_by_id(
        self, client, stub_agent, unique_email
    ):
        stub_agent()
        _, owner_headers = await register_and_login(client, unique_email)
        await _read_stream(client, owner_headers, "private question")
        conversation_id = (
            await client.get("/api/v1/conversations/", headers=owner_headers)
        ).json()[0]["id"]

        _, other_headers = await register_and_login(client, f"other-{unique_email}")
        res = await client.post(
            "/api/v1/chat/stream",
            json={"message": "whose chat is this", "conversation_id": conversation_id},
            headers=other_headers,
        )
        assert res.status_code == 404

        res = await client.get(f"/api/v1/conversations/{conversation_id}", headers=other_headers)
        assert res.status_code == 404


class TestConnectionPoolIsNotLeaked:
    async def test_streaming_returns_every_connection_to_the_pool(
        self, client, stub_agent, unique_email
    ):
        """Guards the invariant the original generator broke.

        It wrote through the request's `Depends(get_db)` session, which
        FastAPI closes before the body runs. SQLAlchemy does not complain —
        it checks out a fresh connection — but nothing ever returns it,
        because the `async with` that would have has already exited. Measured
        against the old pattern, `pool.checkedout()` climbed 1, 2, 3, 4 per
        streamed request until the garbage collector force-terminated
        connections, against a pool of 20 + 10 overflow.

        This is an invariant check rather than a bug-specific reproduction: a
        session left unclosed whose final statement happens to be a COMMIT
        still releases its connection and would pass. It catches the leak,
        not every possible way of causing one.
        """
        from app.db.session import engine

        stub_agent(tokens=("a", "b"))
        _, headers = await register_and_login(client, unique_email)

        for i in range(5):
            await _read_stream(client, headers, f"question {i}")

        # Give the detached persistence tasks a moment to finish and release.
        for _ in range(50):
            if engine.pool.checkedout() == 0:
                break
            await asyncio.sleep(0.02)

        assert engine.pool.checkedout() == 0, "a connection was never returned to the pool"


class TestClientDisconnect:
    async def test_a_partial_reply_survives_the_client_going_away(
        self, client, stub_agent, unique_email
    ):
        """Reading one token and abandoning the response is the disconnect
        case. The write runs as a detached task precisely so it outlives the
        request being torn down."""
        stub_agent(tokens=tuple("abcdefghij"), delay=0.01)
        _, headers = await register_and_login(client, unique_email)

        async with client.stream(
            "POST", "/api/v1/chat/stream", json={"message": "long answer please"}, headers=headers
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                break  # walk away mid-stream

        conversations = (await client.get("/api/v1/conversations/", headers=headers)).json()
        assert len(conversations) == 1
        conversation_id = conversations[0]["id"]

        # The detached write may still be in flight.
        for _ in range(100):
            detail = (
                await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
            ).json()
            if len(detail["messages"]) >= 2:
                break
            await asyncio.sleep(0.02)

        roles = [m["role"] for m in detail["messages"]]
        assert "user" in roles, "the question itself must always be recorded"


class TestSidebarOrdering:
    async def test_the_most_recently_used_conversation_sorts_first(
        self, client, stub_agent, unique_email
    ):
        """`touch()` existed to keep this true and was never called, so the
        sidebar ordered by creation time and an actively-used chat sank."""
        stub_agent(tokens=("ok",))
        _, headers = await register_and_login(client, unique_email)

        await _read_stream(client, headers, "older conversation")
        older = (await client.get("/api/v1/conversations/", headers=headers)).json()[0]["id"]

        await _read_stream(client, headers, "newer conversation")

        # Post another message to the *older* conversation; it should now lead.
        await asyncio.sleep(0.01)
        await _read_stream(client, headers, "revived", conversation_id=older)

        ordered = (await client.get("/api/v1/conversations/", headers=headers)).json()
        assert ordered[0]["id"] == older, "sidebar did not resort after new activity"


class TestRequestValidation:
    async def test_an_oversized_message_is_rejected(self, client, stub_agent, unique_email):
        stub_agent()
        _, headers = await register_and_login(client, unique_email)
        res = await client.post(
            "/api/v1/chat/stream", json={"message": "x" * 100_000}, headers=headers
        )
        assert res.status_code == 422

    async def test_an_empty_message_is_rejected(self, client, stub_agent, unique_email):
        stub_agent()
        _, headers = await register_and_login(client, unique_email)
        res = await client.post("/api/v1/chat/stream", json={"message": ""}, headers=headers)
        assert res.status_code == 422

    async def test_too_many_pinned_documents_is_rejected(self, client, stub_agent, unique_email):
        import uuid as _uuid

        stub_agent()
        _, headers = await register_and_login(client, unique_email)
        res = await client.post(
            "/api/v1/chat/stream",
            json={"message": "compare these", "document_ids": [str(_uuid.uuid4()) for _ in range(50)]},
            headers=headers,
        )
        assert res.status_code == 422

    async def test_chat_requires_authentication(self, client):
        res = await client.post("/api/v1/chat/stream", json={"message": "hello"})
        assert res.status_code == 401
