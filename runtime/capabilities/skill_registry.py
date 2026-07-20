"""SkillRegistry: stores the skills available to the assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.capabilities.events import SkillRegistered, SkillUnregistered
from runtime.capabilities.validation import validate_skill
from runtime.exceptions import SkillNotFoundError, SkillRegistrationError

if TYPE_CHECKING:
    from runtime.capabilities.skill import Skill
    from runtime.context import ApplicationContext

SOURCE = "skill_registry"


class SkillRegistry:
    """Stores and retrieves skills by their `skill_id`.

    The exact counterpart of `ToolRegistry` for skills: an explicit
    lookup table with validation and event emission, no discovery, no
    magic. Mutating methods take the `ApplicationContext` as a
    parameter to reach the `EventBus`, like `PluginRegistry`.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill, application_context: ApplicationContext) -> None:
        """Register `skill` under its `skill_id`.

        Emits `SkillRegistered`.

        Raises:
            CapabilityValidationError: If `skill` fails structural validation.
            SkillRegistrationError: If `skill.skill_id` is already registered.
        """
        validate_skill(skill)
        if skill.skill_id in self._skills:
            raise SkillRegistrationError(f"Skill '{skill.skill_id}' is already registered.")
        self._skills[skill.skill_id] = skill
        application_context.events.emit(
            SkillRegistered(
                source=SOURCE, payload={"skill_id": skill.skill_id, "name": skill.name}
            )
        )

    def unregister(self, skill_id: str, application_context: ApplicationContext) -> None:
        """Remove the skill registered under `skill_id`.

        Emits `SkillUnregistered`.

        Raises:
            SkillNotFoundError: If `skill_id` is not registered.
        """
        skill = self.get(skill_id)
        del self._skills[skill_id]
        application_context.events.emit(
            SkillUnregistered(
                source=SOURCE, payload={"skill_id": skill_id, "name": skill.name}
            )
        )

    def get(self, skill_id: str) -> Skill:
        """Return the skill registered under `skill_id`.

        Raises:
            SkillNotFoundError: If `skill_id` is not registered.
        """
        try:
            return self._skills[skill_id]
        except KeyError:
            raise SkillNotFoundError(f"Skill '{skill_id}' is not registered.") from None

    def has(self, skill_id: str) -> bool:
        """Return True if a skill is registered under `skill_id`."""
        return skill_id in self._skills

    def list(self) -> list[Skill]:
        """Return a snapshot list of registered skills, in registration order."""
        return list(self._skills.values())
