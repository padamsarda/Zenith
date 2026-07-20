"""Tests for the Message dataclass and MessageRole enum."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.conversation.message import Message, MessageRole


def test_expected_roles_exist() -> None:
    expected_names = {"USER", "ASSISTANT", "SYSTEM", "TOOL"}

    assert {role.name for role in MessageRole} == expected_names


def test_roles_have_distinct_values() -> None:
    values = [role.value for role in MessageRole]

    assert len(values) == len(set(values))


def test_message_generates_unique_ids() -> None:
    first = Message(role=MessageRole.USER, content="hello")
    second = Message(role=MessageRole.USER, content="hello")

    assert first.message_id != second.message_id


def test_message_created_at_is_timezone_aware() -> None:
    message = Message(role=MessageRole.USER, content="hello")

    assert message.created_at.tzinfo is not None


def test_message_metadata_defaults_to_empty_dict() -> None:
    message = Message(role=MessageRole.USER, content="hello")

    assert message.metadata == {}


def test_messages_do_not_share_default_metadata() -> None:
    first = Message(role=MessageRole.USER, content="hello")
    second = Message(role=MessageRole.USER, content="hello")
    first.metadata["key"] = "value"

    assert second.metadata == {}


def test_message_is_frozen() -> None:
    message = Message(role=MessageRole.USER, content="hello")

    with pytest.raises(dataclasses.FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


def test_message_carries_role_and_content() -> None:
    message = Message(role=MessageRole.TOOL, content="result", metadata={"tool_id": "clock"})

    assert message.role is MessageRole.TOOL
    assert message.content == "result"
    assert message.metadata == {"tool_id": "clock"}
