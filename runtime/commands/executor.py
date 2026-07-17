"""CommandExecutor: runs a Command's action through a validated, timed,
event-emitting lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from runtime.commands.command import Command
from runtime.commands.context import CommandContext
from runtime.commands.events import (
    CommandCancelled,
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    CommandStarted,
)
from runtime.commands.result import CommandResult
from runtime.commands.status import TERMINAL_STATUSES, CommandStatus
from runtime.commands.validation import validate_command
from runtime.exceptions import CommandCancelledError, CommandValidationError

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

Action = Callable[[CommandContext], Any]

DEFAULT_LOGGER_NAME = "zenith.commands"
SOURCE = "command_executor"


class CommandExecutor:
    """Validates, times, and runs a Command's action, producing a CommandResult.

    The executor is a generic harness: it knows nothing about what an
    action actually does — opening an application, sending an email,
    calling a plugin — only how to run one safely and report the
    outcome. Every future capability that acts on the world should run
    through `execute` rather than being invoked directly, which is what
    makes execution structured and auditable: every run is validated,
    timed, logged, and announced on the `EventBus` the same way.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._executed_ids: set[UUID] = set()

    def validate(self, command: Command) -> None:
        """Raise CommandValidationError if `command` cannot be executed.

        Checks structural validity (name, metadata) and rejects a
        command whose ID has already been executed by this executor.

        Raises:
            CommandValidationError: If validation fails.
        """
        validate_command(command)
        if command.command_id in self._executed_ids:
            raise CommandValidationError(
                f"Command {command.command_id} has already been executed."
            )

    def execute(
        self,
        command: Command,
        application_context: ApplicationContext,
        action: Action,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Validate, run, and time `action`, returning a CommandResult.

        Emits `CommandCreated` then `CommandStarted` before running
        `action`, then exactly one of `CommandCompleted`,
        `CommandFailed`, or `CommandCancelled` after. Always returns a
        `CommandResult` — a validation failure, an exception raised by
        `action`, or a `CommandCancelledError` raised by `action` are
        all reported through the returned result rather than propagated.

        Args:
            command: The command to execute.
            application_context: Supplies the EventBus events are
                emitted on and is wrapped in the CommandContext passed
                to `action`.
            action: The work to perform. Receives a `CommandContext` and
                may return a value, which becomes `CommandResult.data`.
            metadata: Extra data attached to the `CommandContext` passed
                to `action`. Not stored on `command` itself.

        Returns:
            The `CommandResult` describing the outcome.
        """
        events = application_context.events
        events.emit(
            CommandCreated(
                source=SOURCE,
                payload={"command_id": str(command.command_id), "name": command.name},
            )
        )

        start = perf_counter()
        try:
            self.validate(command)
        except CommandValidationError as exc:
            return self._fail(command, application_context, exc, start)

        self._executed_ids.add(command.command_id)
        command.transition_to(CommandStatus.RUNNING)
        events.emit(
            CommandStarted(
                source=SOURCE,
                payload={"command_id": str(command.command_id), "name": command.name},
            )
        )
        self._logger.info("Executing command %s (%s).", command.name, command.command_id)

        context = CommandContext(
            application_context=application_context,
            command_id=command.command_id,
            metadata=metadata or {},
        )

        try:
            data = action(context)
        except CommandCancelledError as exc:
            return self._cancel(command, application_context, exc, start)
        except Exception as exc:
            return self._fail(command, application_context, exc, start)

        duration = perf_counter() - start
        command.transition_to(CommandStatus.COMPLETED)
        self._logger.info(
            "Command %s (%s) completed in %.3fs.", command.name, command.command_id, duration
        )
        events.emit(
            CommandCompleted(
                source=SOURCE,
                payload={"command_id": str(command.command_id), "duration_seconds": duration},
            )
        )
        return CommandResult(
            success=True, message="Command completed.", duration_seconds=duration, data=data
        )

    def _fail(
        self,
        command: Command,
        application_context: ApplicationContext,
        exc: BaseException,
        start: float,
    ) -> CommandResult:
        """Transition `command` to FAILED (if not terminal), log, emit, and build the result."""
        duration = perf_counter() - start
        if command.status not in TERMINAL_STATUSES:
            command.transition_to(CommandStatus.FAILED)
        self._logger.error("Command %s (%s) failed: %s", command.name, command.command_id, exc)
        application_context.events.emit(
            CommandFailed(
                source=SOURCE,
                payload={"command_id": str(command.command_id), "reason": str(exc)},
            )
        )
        return CommandResult(
            success=False, message=str(exc), duration_seconds=duration, exception=exc
        )

    def _cancel(
        self,
        command: Command,
        application_context: ApplicationContext,
        exc: BaseException,
        start: float,
    ) -> CommandResult:
        """Transition `command` to CANCELLED, log, emit, and build the result."""
        duration = perf_counter() - start
        command.transition_to(CommandStatus.CANCELLED)
        self._logger.warning(
            "Command %s (%s) cancelled: %s", command.name, command.command_id, exc
        )
        application_context.events.emit(
            CommandCancelled(
                source=SOURCE,
                payload={"command_id": str(command.command_id), "reason": str(exc)},
            )
        )
        return CommandResult(
            success=False, message=str(exc), duration_seconds=duration, exception=exc
        )
