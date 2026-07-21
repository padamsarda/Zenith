"""MemoryTool: lets the assistant deliberately record, search, and forget."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import MemoryNotFoundError, ToolExecutionError
from runtime.memory.memory import MAX_IMPORTANCE, MIN_IMPORTANCE, Memory, MemoryKind
from runtime.memory.recall import MemoryRecaller, describe_age
from runtime.tools.arguments import optional_bool, optional_int, optional_str, require_str
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.memory"
OPERATIONS = ("remember", "search", "forget")


@dataclass(frozen=True)
class MemoryToolResult:
    """The structured outcome of one memory operation."""

    operation: str
    message: str
    entries: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.operation == "search":
            return "\n".join(self.entries) if self.entries else "(nothing remembered about that)"
        return self.message


class MemoryTool(Tool):
    """Records, searches, and deletes what Zeni knows about the user.

    Deliberately *not* how memory normally reaches a conversation —
    `AssistantContextAssembler` recalls relevant memories into every
    brief automatically, so the model never has to call `search` just to
    know things (ADR 0027). This tool exists for the cases automatic
    recall cannot cover: deliberately committing something ("remember
    that my CubeSat uses 18650 cells"), searching further back than the
    brief's handful of entries, and forgetting something wrong.

    `remember` here always pins: a call to this tool is by definition
    deliberate, which is the same signal the salience rules treat as
    strongest.
    """

    def __init__(
        self,
        *,
        recaller: MemoryRecaller | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._recaller = recaller or MemoryRecaller(recall_limit=10)
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "memory"

    @property
    def name(self) -> str:
        return "Memory"

    @property
    def description(self) -> str:
        return (
            "Deliberately remember a fact for the long term, search everything "
            "remembered so far, or forget something that is wrong. Relevant memories "
            "are already provided automatically each turn — use 'search' only to look "
            "further back than what you were given."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="operation",
                description=f"One of: {', '.join(OPERATIONS)}.",
                required=True,
            ),
            ToolParameter(
                name="content",
                description="For 'remember': the fact to store. For 'search': the query.",
                required=False,
            ),
            ToolParameter(
                name="kind",
                description=(
                    "For 'remember': one of "
                    f"{', '.join(kind.name.lower() for kind in MemoryKind)}. Defaults to fact."
                ),
                required=False,
            ),
            ToolParameter(
                name="importance",
                description=(
                    f"For 'remember': {MIN_IMPORTANCE}-{MAX_IMPORTANCE}. "
                    f"Defaults to {MAX_IMPORTANCE} (deliberate)."
                ),
                required=False,
                type="integer",
            ),
            ToolParameter(
                name="pinned",
                description="For 'remember': keep this permanently recallable. Defaults true.",
                required=False,
                type="boolean",
            ),
            ToolParameter(
                name="memory_id",
                description="For 'forget': the ID of the memory to delete.",
                required=False,
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> MemoryToolResult:
        """Perform one memory operation.

        Raises:
            ToolExecutionError: If `operation` is unrecognized, required
                arguments are missing or malformed, or a memory to forget
                does not exist.
        """
        operation = require_str(arguments, "operation")
        if operation == "remember":
            return self._remember(context, arguments)
        if operation == "search":
            return self._search(context, arguments)
        if operation == "forget":
            return self._forget(context, arguments)
        raise ToolExecutionError(
            f"Unknown memory operation {operation!r}; expected one of {OPERATIONS}."
        )

    def _remember(self, context: CommandContext, arguments: dict[str, Any]) -> MemoryToolResult:
        content = require_str(arguments, "content")
        importance = optional_int(arguments, "importance", default=MAX_IMPORTANCE)
        if not MIN_IMPORTANCE <= importance <= MAX_IMPORTANCE:
            raise ToolExecutionError(
                f"'importance' must be between {MIN_IMPORTANCE} and {MAX_IMPORTANCE}, "
                f"got {importance}."
            )

        memory = Memory(
            content=content,
            kind=self._resolve_kind(arguments),
            importance=importance,
            pinned=optional_bool(arguments, "pinned", default=True),
            source="tool",
        )
        stored = context.application_context.memory.remember(
            memory, context.application_context
        )
        self._logger.info("Remembered: %s", content)
        return MemoryToolResult(
            operation="remember", message=f"Remembered: {stored.content}"
        )

    def _search(self, context: CommandContext, arguments: dict[str, Any]) -> MemoryToolResult:
        query = require_str(arguments, "content")
        now = utc_now()
        recalled = self._recaller.recall(query, context.application_context, now=now)
        entries = tuple(
            f"[{scored.memory.memory_id}] "
            f"({describe_age(scored.memory.occurred_at, now)}) {scored.memory.content}"
            for scored in recalled
        )
        noun = "memory" if len(entries) == 1 else "memories"
        return MemoryToolResult(
            operation="search", message=f"{len(entries)} {noun} found.", entries=entries
        )

    def _forget(self, context: CommandContext, arguments: dict[str, Any]) -> MemoryToolResult:
        raw_id = require_str(arguments, "memory_id")
        try:
            memory_id = UUID(raw_id)
        except ValueError as exc:
            raise ToolExecutionError(f"'memory_id' must be a UUID, got {raw_id!r}.") from exc

        try:
            context.application_context.memory.forget(memory_id, context.application_context)
        except MemoryNotFoundError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return MemoryToolResult(operation="forget", message=f"Forgot memory {memory_id}.")

    def _resolve_kind(self, arguments: dict[str, Any]) -> MemoryKind:
        """Resolve the `kind` argument to a `MemoryKind`, defaulting to FACT."""
        raw = optional_str(arguments, "kind")
        if raw is None:
            return MemoryKind.FACT
        try:
            return MemoryKind[raw.strip().upper()]
        except KeyError as exc:
            valid = ", ".join(kind.name.lower() for kind in MemoryKind)
            raise ToolExecutionError(
                f"Unknown memory kind {raw!r}; expected one of {valid}."
            ) from exc
