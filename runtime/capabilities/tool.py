"""Tool: an invocable capability the assistant can act with."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext


@dataclass(frozen=True)
class ToolParameter:
    """Declares one argument a tool accepts.

    `type` is a JSON Schema primitive type name (`"string"`, `"number"`,
    `"boolean"`, `"integer"`, `"array"`, `"object"`), defaulting to
    `"string"` so every existing declaration keeps its current meaning.
    This is the additive extension ADR 0013 anticipated: parameters were
    deliberately thin until a real provider integration needed a type
    vocabulary to build tool-call schemas from (`runtime.providers.claude`
    is the first to read it).
    """

    name: str
    description: str | None = None
    required: bool = True
    type: str = "string"


class Tool(ABC):
    """Base class for every invocable capability.

    A tool is a single action the assistant can take on the world —
    reading a file, sending a message, launching an application. Tools
    never run themselves: the `AssistantEngine` executes each invocation
    as a `Command` through the `CommandExecutor`, which is what makes
    every tool run validated, timed, logged, and announced on the
    `EventBus` like any other action Zenith performs. The
    `CommandContext` a tool receives in `invoke` is that command's
    context, giving it access to the shared `ApplicationContext`.

    Contrast with `Skill` (`runtime.capabilities.skill`): a tool *acts*;
    a skill contributes *know-how* to the provider's brief.
    """

    @property
    @abstractmethod
    def tool_id(self) -> str:
        """Stable, author-chosen identifier — how providers name this tool."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """What the tool does — shown to providers choosing capabilities."""

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        """The arguments this tool accepts. Defaults to none."""
        return ()

    @abstractmethod
    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        """Perform the tool's action and return its result.

        Called inside a `Command` action by the `AssistantEngine`; a
        raised exception fails that command, is reported as a failed
        tool call to the provider, and never propagates out of the
        request pipeline.

        Args:
            context: The executing command's context.
            arguments: The invocation arguments supplied by the provider.
        """
