"""Tests for the CommandExecutor."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.commands.command import Command
from runtime.commands.context import CommandContext
from runtime.commands.events import (
    CommandCancelled,
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    CommandStarted,
)
from runtime.commands.executor import CommandExecutor
from runtime.commands.result import CommandResult
from runtime.commands.status import CommandStatus
from runtime.context import ApplicationContext
from shared.events.event import Event
from runtime.exceptions import CommandCancelledError, CommandExecutionError, CommandValidationError


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.command_executor"))


ALL_COMMAND_EVENT_TYPES = (
    CommandCreated,
    CommandStarted,
    CommandCompleted,
    CommandFailed,
    CommandCancelled,
)


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in ALL_COMMAND_EVENT_TYPES:
        app_context.events.subscribe(event_type, received.append)
    return received


# --- validate() ---------------------------------------------------------


def test_validate_passes_for_valid_new_command() -> None:
    executor = CommandExecutor()

    executor.validate(Command(name="test"))


def test_validate_raises_for_invalid_name() -> None:
    executor = CommandExecutor()

    with pytest.raises(CommandValidationError):
        executor.validate(Command(name=""))


def test_validate_raises_for_invalid_metadata() -> None:
    executor = CommandExecutor()
    command = Command(name="test", metadata="bad")  # type: ignore[arg-type]

    with pytest.raises(CommandValidationError):
        executor.validate(command)


def test_validate_raises_for_already_executed_command_id() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")
    executor.execute(command, app_context, lambda ctx: None)

    with pytest.raises(CommandValidationError):
        executor.validate(command)


def test_validate_does_not_flag_unexecuted_command_as_duplicate() -> None:
    executor = CommandExecutor()
    executor.validate(Command(name="a"))
    executor.validate(Command(name="b"))


# --- execute(): return type and success path ----------------------------


def test_execute_returns_command_result() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert isinstance(result, CommandResult)


def test_execute_never_returns_none() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert result is not None


def test_execute_success_sets_success_true() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert result.success is True


def test_execute_success_carries_action_return_value_as_data() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: {"answer": 42})

    assert result.data == {"answer": 42}


def test_execute_success_has_no_exception() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert result.exception is None


def test_execute_success_duration_is_non_negative() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert result.duration_seconds >= 0.0


def test_execute_success_transitions_command_to_completed() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")

    executor.execute(command, app_context, lambda ctx: None)

    assert command.status is CommandStatus.COMPLETED


def test_execute_passes_command_context_to_action() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")
    captured: list[CommandContext] = []

    executor.execute(command, app_context, captured.append)

    assert len(captured) == 1
    assert isinstance(captured[0], CommandContext)


def test_execute_command_context_carries_matching_command_id() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")
    captured: list[CommandContext] = []

    executor.execute(command, app_context, captured.append)

    assert captured[0].command_id == command.command_id


def test_execute_command_context_carries_application_context() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    captured: list[CommandContext] = []

    executor.execute(Command(name="test"), app_context, captured.append)

    assert captured[0].application_context is app_context


def test_execute_passes_extra_metadata_to_command_context() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    captured: list[CommandContext] = []

    executor.execute(
        Command(name="test"), app_context, captured.append, metadata={"trace": "abc"}
    )

    assert captured[0].metadata == {"trace": "abc"}


# --- execute(): validation failure path ----------------------------------


def test_execute_with_invalid_command_returns_failed_result() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name=""), app_context, lambda ctx: None)

    assert result.success is False


def test_execute_with_invalid_command_does_not_call_action() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    called = []

    executor.execute(Command(name=""), app_context, lambda ctx: called.append(True))

    assert called == []


def test_execute_with_invalid_command_sets_status_failed() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="")

    executor.execute(command, app_context, lambda ctx: None)

    assert command.status is CommandStatus.FAILED


def test_execute_with_invalid_command_result_carries_validation_exception() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    result = executor.execute(Command(name=""), app_context, lambda ctx: None)

    assert isinstance(result.exception, CommandValidationError)


def test_execute_with_duplicate_command_does_not_crash_after_terminal_status() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")
    executor.execute(command, app_context, lambda ctx: None)

    result = executor.execute(command, app_context, lambda ctx: None)

    assert result.success is False
    assert command.status is CommandStatus.COMPLETED


# --- execute(): action failure path ---------------------------------------


def test_execute_action_raising_returns_failed_result() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    result = executor.execute(Command(name="test"), app_context, failing_action)

    assert result.success is False
    assert result.message == "boom"


def test_execute_action_raising_sets_status_failed() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    executor.execute(command, app_context, failing_action)

    assert command.status is CommandStatus.FAILED


def test_execute_action_raising_carries_original_exception() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    exc = RuntimeError("kaboom")

    def failing_action(ctx: CommandContext) -> None:
        raise exc

    result = executor.execute(Command(name="test"), app_context, failing_action)

    assert result.exception is exc


def test_execute_command_execution_error_is_treated_as_failure() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    def failing_action(ctx: CommandContext) -> None:
        raise CommandExecutionError("structured failure")

    result = executor.execute(Command(name="test"), app_context, failing_action)

    assert result.success is False
    assert isinstance(result.exception, CommandExecutionError)


def test_execute_does_not_propagate_action_exception() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    executor.execute(Command(name="test"), app_context, failing_action)  # must not raise


# --- execute(): cancellation path ------------------------------------------


def test_execute_action_raising_cancelled_error_returns_failed_result() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    def cancelling_action(ctx: CommandContext) -> None:
        raise CommandCancelledError("stopped by user")

    result = executor.execute(Command(name="test"), app_context, cancelling_action)

    assert result.success is False
    assert result.message == "stopped by user"


def test_execute_action_raising_cancelled_error_sets_status_cancelled() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")

    def cancelling_action(ctx: CommandContext) -> None:
        raise CommandCancelledError("stopped by user")

    executor.execute(command, app_context, cancelling_action)

    assert command.status is CommandStatus.CANCELLED


def test_execute_cancellation_is_distinct_from_generic_failure() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    def cancelling_action(ctx: CommandContext) -> None:
        raise CommandCancelledError("stopped")

    executor.execute(Command(name="test"), app_context, cancelling_action)

    names = [event.name for event in received]
    assert "CommandCancelled" in names
    assert "CommandFailed" not in names


# --- execute(): event emission ----------------------------------------------


def test_execute_success_emits_created_started_completed_in_order() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    executor.execute(Command(name="test"), app_context, lambda ctx: None)

    names = [event.name for event in received]
    assert names == ["CommandCreated", "CommandStarted", "CommandCompleted"]


def test_execute_failure_emits_created_started_failed_in_order() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    executor.execute(Command(name="test"), app_context, failing_action)

    names = [event.name for event in received]
    assert names == ["CommandCreated", "CommandStarted", "CommandFailed"]


def test_execute_validation_failure_emits_created_and_failed_only() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    executor.execute(Command(name=""), app_context, lambda ctx: None)

    names = [event.name for event in received]
    assert names == ["CommandCreated", "CommandFailed"]


def test_execute_events_carry_matching_command_id() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)
    command = Command(name="test")

    executor.execute(command, app_context, lambda ctx: None)

    for event in received:
        assert event.payload["command_id"] == str(command.command_id)


def test_execute_events_use_command_executor_as_source() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    executor.execute(Command(name="test"), app_context, lambda ctx: None)

    for event in received:
        assert event.source == "command_executor"


def test_execute_completed_event_carries_duration() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(CommandCompleted, received.append)

    executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert "duration_seconds" in received[0].payload
    assert received[0].payload["duration_seconds"] >= 0.0


def test_execute_failed_event_carries_reason() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(CommandFailed, received.append)

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    executor.execute(Command(name="test"), app_context, failing_action)

    assert received[0].payload["reason"] == "boom"


def test_execute_cancelled_event_carries_reason() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(CommandCancelled, received.append)

    def cancelling_action(ctx: CommandContext) -> None:
        raise CommandCancelledError("nope")

    executor.execute(Command(name="test"), app_context, cancelling_action)

    assert received[0].payload["reason"] == "nope"


def test_execute_events_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    # ApplicationContext's EventBus defaults to the "zenith.events" logger
    # (see shared.events.bus.DEFAULT_LOGGER_NAME); EventLogger writes one
    # INFO line per emitted event automatically.
    app_context = make_application_context()
    executor = CommandExecutor()

    with caplog.at_level(logging.INFO, logger="zenith.events"):
        executor.execute(Command(name="test"), app_context, lambda ctx: None)

    messages = " ".join(caplog.messages)
    assert "CommandCreated" in messages
    assert "CommandStarted" in messages
    assert "CommandCompleted" in messages


# --- execute(): executor logging --------------------------------------------


def test_execute_success_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.command_executor.success_log")
    executor = CommandExecutor(logger=logger)
    app_context = make_application_context()

    with caplog.at_level(logging.INFO, logger="test.command_executor.success_log"):
        executor.execute(Command(name="test"), app_context, lambda ctx: None)

    assert any("completed" in message for message in caplog.messages)


def test_execute_failure_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.command_executor.failure_log")
    executor = CommandExecutor(logger=logger)
    app_context = make_application_context()

    def failing_action(ctx: CommandContext) -> None:
        raise ValueError("boom")

    with caplog.at_level(logging.ERROR, logger="test.command_executor.failure_log"):
        executor.execute(Command(name="test"), app_context, failing_action)

    assert any("failed" in message for message in caplog.messages)


def test_execute_cancellation_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.command_executor.cancel_log")
    executor = CommandExecutor(logger=logger)
    app_context = make_application_context()

    def cancelling_action(ctx: CommandContext) -> None:
        raise CommandCancelledError("nope")

    with caplog.at_level(logging.WARNING, logger="test.command_executor.cancel_log"):
        executor.execute(Command(name="test"), app_context, cancelling_action)

    assert any("cancelled" in message for message in caplog.messages)


# --- executor is a generic, stateless-per-action harness --------------------


def test_executor_runs_multiple_distinct_commands() -> None:
    executor = CommandExecutor()
    app_context = make_application_context()

    first = executor.execute(Command(name="a"), app_context, lambda ctx: "a-result")
    second = executor.execute(Command(name="b"), app_context, lambda ctx: "b-result")

    assert first.data == "a-result"
    assert second.data == "b-result"


def test_two_executors_track_duplicate_ids_independently() -> None:
    first_executor = CommandExecutor()
    second_executor = CommandExecutor()
    app_context = make_application_context()
    command = Command(name="test")

    first_executor.execute(command, app_context, lambda ctx: None)

    # A different, unexecuted command against the second executor is fine.
    other_command = Command(name="test")
    result = second_executor.execute(other_command, app_context, lambda ctx: None)

    assert result.success is True
