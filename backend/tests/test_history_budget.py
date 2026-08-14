"""Conversation history is bounded by size, not just by turn count.

MAX_HISTORY_MESSAGES caps how many turns are replayed, which says nothing
about how large they are — twenty messages can be twenty words or twenty
thousand. Since the retrieved context is appended on top of all of them, an
unbounded history is an unbounded prompt, and the failure arrives as a
provider context-window error rather than as anything this system can act on.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.agent import ChatMessage, _history_within_budget


def _messages(count: int, size: int) -> list[ChatMessage]:
    return [
        ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"{i}" * size)
        for i in range(count)
    ]


class TestTurnCountCap:
    def test_history_is_capped_at_max_history_messages(self):
        history = _messages(settings.MAX_HISTORY_MESSAGES + 10, size=10)
        assert len(_history_within_budget(history)) <= settings.MAX_HISTORY_MESSAGES

    def test_a_short_history_is_returned_unchanged(self):
        history = _messages(4, size=10)
        assert _history_within_budget(history) == history


class TestCharacterBudget:
    def test_a_few_enormous_messages_are_trimmed(self):
        """Well under the turn cap, far over the character budget."""
        history = _messages(6, size=settings.MAX_HISTORY_CHARS)
        kept = _history_within_budget(history)

        assert len(kept) < len(history)
        assert sum(len(m.content) for m in kept) <= settings.MAX_HISTORY_CHARS * 2

    def test_trimming_drops_the_oldest_turns_first(self):
        history = _messages(6, size=settings.MAX_HISTORY_CHARS // 2)
        kept = _history_within_budget(history)

        assert kept, "at least the most recent turn must survive"
        # The retained window ends at the newest message.
        assert kept[-1] is history[-1]
        # And it is a contiguous suffix of the input.
        assert kept == history[-len(kept) :]

    def test_a_single_oversized_message_is_still_kept(self):
        """Dropping everything would send the model a question with no
        history at all; one over-budget turn is better than none."""
        history = _messages(1, size=settings.MAX_HISTORY_CHARS * 3)
        assert len(_history_within_budget(history)) == 1

    def test_empty_history_is_handled(self):
        assert _history_within_budget([]) == []


class TestRequestBounds:
    def test_the_message_field_rejects_oversized_input(self):
        from pydantic import ValidationError

        from app.schemas.conversation import ChatRequest

        ChatRequest(message="x" * settings.MAX_MESSAGE_CHARS)
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * (settings.MAX_MESSAGE_CHARS + 1))

    def test_the_message_field_rejects_empty_input(self):
        from pydantic import ValidationError

        from app.schemas.conversation import ChatRequest

        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_pinned_documents_are_bounded(self):
        import uuid

        from pydantic import ValidationError

        from app.schemas.conversation import ChatRequest

        too_many = [uuid.uuid4() for _ in range(settings.MAX_PINNED_DOCUMENTS + 1)]
        with pytest.raises(ValidationError):
            ChatRequest(message="compare these", document_ids=too_many)
