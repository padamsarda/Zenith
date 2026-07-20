"""CapabilityCatalog: a deterministic, read-only view of what Zenith can do."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from runtime.capabilities.tool import ToolParameter

if TYPE_CHECKING:
    from runtime.capabilities.skill_registry import SkillRegistry
    from runtime.capabilities.tool_registry import ToolRegistry


class CapabilityKind(Enum):
    """What kind of capability a descriptor describes."""

    TOOL = auto()
    SKILL = auto()


@dataclass(frozen=True)
class CapabilityDescriptor:
    """A declarative description of one capability.

    This is the discovery surface: providers receive tool descriptors in
    every brief (never the `Tool` objects themselves), and anything that
    wants to know what Zenith can currently do — a UI, a plugin, a
    provider — reads descriptors rather than reaching into the
    registries.
    """

    kind: CapabilityKind
    capability_id: str
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()


@dataclass(frozen=True)
class CapabilityCatalog:
    """A snapshot of every registered capability, as descriptors.

    Built on demand by `build_catalog` and never cached: like the
    Engineering Manager's session briefs (ADR 0010), a catalog is
    derived from current state at the moment it is needed, so it can
    never go stale.
    """

    tools: tuple[CapabilityDescriptor, ...]
    skills: tuple[CapabilityDescriptor, ...]

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        """All descriptors — tools first, then skills."""
        return self.tools + self.skills


def build_catalog(tools: ToolRegistry, skills: SkillRegistry) -> CapabilityCatalog:
    """Build a `CapabilityCatalog` snapshot from the two registries.

    Descriptors are ordered by capability ID, so two catalogs built from
    the same registrations are identical regardless of registration
    order — briefs composed from a catalog are reproducible.
    """
    tool_descriptors = tuple(
        CapabilityDescriptor(
            kind=CapabilityKind.TOOL,
            capability_id=tool.tool_id,
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
        )
        for tool in sorted(tools.list(), key=lambda tool: tool.tool_id)
    )
    skill_descriptors = tuple(
        CapabilityDescriptor(
            kind=CapabilityKind.SKILL,
            capability_id=skill.skill_id,
            name=skill.name,
            description=skill.description,
        )
        for skill in sorted(skills.list(), key=lambda skill: skill.skill_id)
    )
    return CapabilityCatalog(tools=tool_descriptors, skills=skill_descriptors)
