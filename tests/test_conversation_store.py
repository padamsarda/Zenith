"""Tests for the ConversationStore abstract contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.conversation.in_memory_store import InMemoryConversationStore
from runtime.conversation.sqlite.store import SQLiteConversationStore
from runtime.conversation.store import ConversationStore


def test_conversation_store_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ConversationStore()  # type: ignore[abstract]


def test_incomplete_subclass_cannot_be_instantiated() -> None:
    class IncompleteStore(ConversationStore):
        def create(self, application_context: object, **kwargs: object) -> object:
            pass

    with pytest.raises(TypeError):
        IncompleteStore()  # type: ignore[abstract]


def test_in_memory_store_is_a_conversation_store() -> None:
    assert isinstance(InMemoryConversationStore(), ConversationStore)


def test_sqlite_store_is_a_conversation_store(tmp_path: Path) -> None:
    store = SQLiteConversationStore(tmp_path / "conversations.db")

    assert isinstance(store, ConversationStore)
    store.close()
