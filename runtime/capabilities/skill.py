"""Skill: packaged know-how that shapes the provider's brief."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest


class Skill(ABC):
    """Base class for every skill.

    A skill is instructional, not executable: when active for a request,
    its `instructions` text is included in the brief the
    `AssistantContextAssembler` composes for the provider. This is the
    same philosophy as the Engineering Manager's context assembly
    (ADR 0010) — context is derived deterministically at the moment it
    is needed, never stored — applied to assistant behavior.

    A skill becomes active for a request in either of two ways:

    - the request names it, in `request.metadata["skills"]`;
    - the skill's own `applies_to(request)` returns True.

    Contrast with `Tool` (`runtime.capabilities.tool`): a tool *acts*;
    a skill contributes *know-how*. A behavior that needs both ships a
    skill (the instructions) alongside the tools it teaches the
    provider to use.
    """

    @property
    @abstractmethod
    def skill_id(self) -> str:
        """Stable, author-chosen identifier — how requests name this skill."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """What the skill teaches — shown in capability discovery."""

    @abstractmethod
    def instructions(self, request: AssistantRequest) -> str:
        """Return the instruction text contributed to the provider's brief.

        Called once per assembled brief, with the request being served,
        so instructions may be tailored to it. Must be deterministic for
        a given request — the assembler guarantees briefs can be
        recomposed identically, and a skill that answers differently on
        each call would break that.
        """

    def applies_to(self, request: AssistantRequest) -> bool:
        """Return True if this skill should activate for `request` unasked.

        Defaults to False: skills activate only when a request names
        them. Override to opt into automatic activation.
        """
        return False
