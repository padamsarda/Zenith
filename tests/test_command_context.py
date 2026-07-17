"""Tests for CommandContext and CancellationToken."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CancellationToken, CommandContext
from runtime.context import ApplicationContext


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.command_context"))


def test_cancellation_token_defaults_to_not_cancelled() -> None:
    token = CancellationToken()

    assert token.cancelled is False


def test_cancellation_token_is_immutable() -> None:
    token = CancellationToken()

    with pytest.raises(AttributeError):
        token.cancelled = True  # type: ignore[misc]


def test_command_context_carries_application_context() -> None:
    app_context = make_application_context()
    command_id = uuid4()

    context = CommandContext(application_context=app_context, command_id=command_id)

    assert context.application_context is app_context


def test_command_context_carries_command_id() -> None:
    app_context = make_application_context()
    command_id = uuid4()

    context = CommandContext(application_context=app_context, command_id=command_id)

    assert context.command_id == command_id


def test_command_context_started_at_is_timezone_aware() -> None:
    app_context = make_application_context()

    context = CommandContext(application_context=app_context, command_id=uuid4())

    assert isinstance(context.started_at, datetime)
    assert context.started_at.tzinfo == timezone.utc


def test_command_context_has_default_cancellation_token() -> None:
    app_context = make_application_context()

    context = CommandContext(application_context=app_context, command_id=uuid4())

    assert isinstance(context.cancellation_token, CancellationToken)
    assert context.cancellation_token.cancelled is False


def test_command_context_metadata_defaults_to_empty_dict() -> None:
    app_context = make_application_context()

    context = CommandContext(application_context=app_context, command_id=uuid4())

    assert context.metadata == {}


def test_command_context_metadata_can_carry_data() -> None:
    app_context = make_application_context()

    context = CommandContext(
        application_context=app_context, command_id=uuid4(), metadata={"reason": "test"}
    )

    assert context.metadata == {"reason": "test"}


def test_command_context_is_immutable() -> None:
    app_context = make_application_context()
    context = CommandContext(application_context=app_context, command_id=uuid4())

    with pytest.raises(AttributeError):
        context.command_id = uuid4()  # type: ignore[misc]


def test_two_command_contexts_have_independent_metadata() -> None:
    app_context = make_application_context()
    first = CommandContext(application_context=app_context, command_id=uuid4(), metadata={"a": 1})
    second = CommandContext(application_context=app_context, command_id=uuid4())

    assert second.metadata == {}
    assert first.metadata != second.metadata
