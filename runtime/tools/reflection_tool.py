"""ReflectionTool: on-demand reflection, and reading what has been concluded."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.memory.recall import describe_age
from runtime.reflection.reflection import ReflectionKind
from runtime.reflection.service import ReflectionService
from runtime.tools.arguments import optional_int, optional_str, require_str
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.reflection"
OPERATIONS = ("reflect", "list")
DEFAULT_LIST_LIMIT = 5


@dataclass(frozen=True)
class ReflectionToolResult:
    """The structured outcome of one reflection operation."""

    operation: str
    message: str
    entries: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.entries:
            return "\n\n".join(self.entries)
        return self.message


class ReflectionTool(Tool):
    """Performs a fresh reflection on request, or reads past ones.

    Level three of the reflection design (ADR 0029). Levels one and two
    run on their own — a summary when a conversation ends, a synthesis
    on a schedule — and neither needs a tool. This exists for when the
    user asks directly: "what have you learned about me", "what patterns
    do you see", "what should I focus on next". Those want a *fresh*
    analysis of the material relevant to the question, not a stored
    answer to a different one.

    `list` reads what has already been concluded, which is the cheap
    path: it makes no model call, so a question that a recent deep
    reflection already answers need not pay for a new one.
    """

    def __init__(
        self,
        service: ReflectionService,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create the tool.

        Args:
            service: The `ReflectionService` performing reflections.
                Required — unlike the other tools, this one cannot supply
                a sensible default, since reflection needs a model that
                only the deployment knows how to reach.
            logger: Defaults to a module logger.
        """
        self._service = service
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "reflection"

    @property
    def name(self) -> str:
        return "Reflection"

    @property
    def description(self) -> str:
        return (
            "Answers questions about what you have learned about the user over time — "
            "patterns, recurring themes, long-term goals, what they should focus on. "
            "Use 'reflect' for a fresh analysis of a specific question; use 'list' to "
            "read conclusions already drawn, which is cheaper and often enough."
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
                name="question",
                description="For 'reflect': what the user wants to understand.",
                required=False,
            ),
            ToolParameter(
                name="kind",
                description=(
                    "For 'list': filter to one of "
                    f"{', '.join(kind.name.lower() for kind in ReflectionKind)}."
                ),
                required=False,
            ),
            ToolParameter(
                name="limit",
                description=f"For 'list': how many to return. Defaults to {DEFAULT_LIST_LIMIT}.",
                required=False,
                type="integer",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> ReflectionToolResult:
        """Perform one reflection operation.

        Raises:
            ToolExecutionError: If `operation` is unrecognized or its
                required arguments are missing or malformed.
        """
        operation = require_str(arguments, "operation")
        if operation == "reflect":
            return self._reflect(context, arguments)
        if operation == "list":
            return self._list(context, arguments)
        raise ToolExecutionError(
            f"Unknown reflection operation {operation!r}; expected one of {OPERATIONS}."
        )

    def _reflect(
        self, context: CommandContext, arguments: dict[str, Any]
    ) -> ReflectionToolResult:
        question = require_str(arguments, "question")
        self._logger.info("On-demand reflection: %s", question)

        reflection = self._service.reflect_on_demand(question, context.application_context)
        if reflection is None:
            return ReflectionToolResult(
                operation="reflect",
                message="Not enough remembered yet to draw anything meaningful from.",
            )
        return ReflectionToolResult(
            operation="reflect",
            message=f"{reflection.content}\n\n(drawn from {reflection.source_count} memories)",
        )

    def _list(self, context: CommandContext, arguments: dict[str, Any]) -> ReflectionToolResult:
        kind = self._resolve_kind(arguments)
        limit = optional_int(arguments, "limit", default=DEFAULT_LIST_LIMIT)
        if limit < 1:
            raise ToolExecutionError(f"'limit' must be at least 1, got {limit}.")

        now = utc_now()
        found = context.application_context.reflections.list(kind=kind, limit=limit)
        if not found:
            return ReflectionToolResult(
                operation="list", message="Nothing has been concluded yet."
            )

        entries = tuple(
            f"({describe_age(reflection.created_at, now)}, "
            f"{reflection.kind.name.lower()}, from {reflection.source_count} memories)\n"
            f"{reflection.content}"
            for reflection in found
        )
        noun = "reflection" if len(entries) == 1 else "reflections"
        return ReflectionToolResult(
            operation="list", message=f"{len(entries)} {noun}.", entries=entries
        )

    def _resolve_kind(self, arguments: dict[str, Any]) -> ReflectionKind | None:
        """Resolve the optional `kind` filter, or None for all kinds."""
        raw = optional_str(arguments, "kind")
        if raw is None:
            return None
        try:
            return ReflectionKind[raw.strip().upper()]
        except KeyError as exc:
            valid = ", ".join(kind.name.lower() for kind in ReflectionKind)
            raise ToolExecutionError(
                f"Unknown reflection kind {raw!r}; expected one of {valid}."
            ) from exc
