"""Concrete events emitted by the assistant engine."""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class RequestReceived(Event):
    """Emitted when a request enters the pipeline via `AssistantEngine.handle`."""


@dataclass(frozen=True)
class RequestCompleted(Event):
    """Emitted when a request finishes with a final assistant reply."""


@dataclass(frozen=True)
class RequestFailed(Event):
    """Emitted when a request fails validation, is rejected, or errors."""


@dataclass(frozen=True)
class ToolCallRequested(Event):
    """Emitted when a provider turn requests a tool invocation."""


@dataclass(frozen=True)
class ToolCallDenied(Event):
    """Emitted when the permission policy or a hook blocks a tool call."""


@dataclass(frozen=True)
class ToolCallCompleted(Event):
    """Emitted when a requested tool call executes successfully."""


@dataclass(frozen=True)
class ToolCallFailed(Event):
    """Emitted when a requested tool call is unknown or its execution fails."""
