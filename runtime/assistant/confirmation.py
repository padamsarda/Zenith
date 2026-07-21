"""ConfirmationHook: a human checkpoint in front of destructive tool calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from runtime.assistant.hooks import AssistantHook
from runtime.exceptions import ToolCallVetoedError

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.context import ApplicationContext
    from runtime.providers.base import ToolCall

DEFAULT_LOGGER_NAME = "zenith.assistant.confirmation"

# `shell` has no sub-operation to distinguish "safe" from "destructive" —
# classifying a command string by content would be unreliable and
# gameable, so every call is gated. `filesystem`'s read-only operations
# (read/list/mkdir/exists) cannot destroy anything already there, so only
# `write` (can overwrite existing content) and `delete` need a checkpoint.
# `app_control`'s `close` (ADR 0024's follow-up) force-terminates a
# process and can lose unsaved work the same way `filesystem.delete`
# loses a file; `list`/`switch` are read-only/reversible and stay clear.
# `memory`'s `prune` deletes many memories in one call, and `forget`
# deletes one — both irreversible, both worth a checkpoint. `remember`
# and `search` add or read and stay clear (ADR 0028).
_ALWAYS_GATED_TOOL_IDS = frozenset({"shell"})
_GATED_FILESYSTEM_OPERATIONS = frozenset({"write", "delete"})
_GATED_APP_CONTROL_OPERATIONS = frozenset({"close"})
_GATED_MEMORY_OPERATIONS = frozenset({"forget", "prune"})

Confirmer = Callable[[str], bool]


def console_confirmer(description: str) -> bool:
    """Ask on the real console whether to proceed. `y`/`yes` (any case) approves.

    Blocks on `input()`, which reads the same stdin `ConsoleInterface`
    reads its next line from — consistent with the runtime's synchronous,
    single-threaded design (ADR 0007). A future non-console interface
    supplies its own `Confirmer` rather than reusing this one.
    """
    answer = input(f"Zeni wants to {description}. Allow? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


class ConfirmationHook(AssistantHook):
    """Requires explicit approval before a destructive tool call runs.

    Sits behind the `PermissionPolicy`: a policy decides whether a tool
    may run *at all* for a deployment; this decides whether *this
    particular call* may proceed right now, for the subset of calls that
    can destroy something irrecoverably (`shell`'s arbitrary commands,
    `filesystem`'s `write`/`delete`, `app_control`'s `close`, and
    `memory`'s `forget`/`prune`). Everything else — including
    `AppLauncherTool`, `app_control`'s own `list`/`switch`,
    `MediaControlTool` (ADR 0024), and `memory`'s `remember`/`search` —
    is unaffected, since none of those can lose data.

    Declining raises `ToolCallVetoedError`, which `ToolCallRunner`
    records as a denial the provider sees on its next turn — the request
    continues, it just doesn't get what it asked for (ADR 0013).
    """

    def __init__(
        self,
        *,
        confirmer: Confirmer = console_confirmer,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a ConfirmationHook.

        Args:
            confirmer: Asks for approval and returns whether it was
                given. Injectable so tests never block on real input.
            logger: Defaults to a module logger.
        """
        self._confirmer = confirmer
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def before_tool(
        self,
        request: AssistantRequest,
        call: ToolCall,
        application_context: ApplicationContext,
    ) -> None:
        """Veto `call` if it is gated and the confirmer declines it.

        Raises:
            ToolCallVetoedError: If the call is gated and not approved.
        """
        description = self._describe_if_gated(call)
        if description is None:
            return

        if self._confirmer(description):
            self._logger.info("Approved: %s", description)
            return

        self._logger.info("Declined: %s", description)
        raise ToolCallVetoedError(f"Declined: {description}")

    def _describe_if_gated(self, call: ToolCall) -> str | None:
        """Return a human-readable description of `call` if it needs approval, else None."""
        if call.tool_id in _ALWAYS_GATED_TOOL_IDS:
            command = call.arguments.get("command", "")
            return f"run shell command {command!r}"

        if call.tool_id == "filesystem":
            operation = call.arguments.get("operation")
            if operation in _GATED_FILESYSTEM_OPERATIONS:
                path = call.arguments.get("path", "")
                return f"{operation} filesystem path {path!r}"

        if call.tool_id == "app_control":
            operation = call.arguments.get("operation")
            if operation in _GATED_APP_CONTROL_OPERATIONS:
                app_name = call.arguments.get("app_name", "")
                return f"close application {app_name!r}"

        if call.tool_id == "memory":
            operation = call.arguments.get("operation")
            if operation in _GATED_MEMORY_OPERATIONS:
                return f"{operation} from memory"

        return None
