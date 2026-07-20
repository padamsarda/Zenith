"""Concrete events emitted by the capability registries."""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class ToolRegistered(Event):
    """Emitted when a tool is registered with the ToolRegistry."""


@dataclass(frozen=True)
class ToolUnregistered(Event):
    """Emitted when a tool is unregistered from the ToolRegistry."""


@dataclass(frozen=True)
class SkillRegistered(Event):
    """Emitted when a skill is registered with the SkillRegistry."""


@dataclass(frozen=True)
class SkillUnregistered(Event):
    """Emitted when a skill is unregistered from the SkillRegistry."""
