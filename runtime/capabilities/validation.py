"""Validation helpers for the capability framework.

Mirrors `runtime.commands.validation` and `runtime.plugins.validation`:
small, explicit guard functions that raise on failure, used at the
framework boundary (tool and skill registration).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.capabilities.tool import ToolParameter
from runtime.exceptions import CapabilityValidationError
from shared.utils.text_utils import is_blank_or_padded

if TYPE_CHECKING:
    from runtime.capabilities.skill import Skill
    from runtime.capabilities.tool import Tool


def validate_capability_id(capability_id: str) -> None:
    """Raise CapabilityValidationError if `capability_id` is not a usable identifier.

    A valid identifier is a non-empty string with no leading or trailing
    whitespace — the same rule service names and command names follow.
    """
    if is_blank_or_padded(capability_id):
        raise CapabilityValidationError(f"Invalid capability identifier: {capability_id!r}")


def validate_capability_text(value: str, field_name: str) -> None:
    """Raise CapabilityValidationError if `value` is not usable display text."""
    if not isinstance(value, str) or not value.strip():
        raise CapabilityValidationError(
            f"Capability {field_name} must be non-empty text, got {value!r}"
        )


def validate_tool(tool: Tool) -> None:
    """Raise CapabilityValidationError if `tool` fails structural validation.

    Checks the tool's identifier, name, description, and parameter
    declaration.
    """
    validate_capability_id(tool.tool_id)
    validate_capability_text(tool.name, "name")
    validate_capability_text(tool.description, "description")
    for parameter in tool.parameters:
        if not isinstance(parameter, ToolParameter):
            raise CapabilityValidationError(
                f"Tool {tool.tool_id!r} parameters must be ToolParameter instances, "
                f"got {parameter!r}"
            )
        validate_capability_id(parameter.name)


def validate_skill(skill: Skill) -> None:
    """Raise CapabilityValidationError if `skill` fails structural validation.

    Checks the skill's identifier, name, and description.
    """
    validate_capability_id(skill.skill_id)
    validate_capability_text(skill.name, "name")
    validate_capability_text(skill.description, "description")
