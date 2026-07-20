"""ToolRegistry: stores the tools available to the assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.capabilities.events import ToolRegistered, ToolUnregistered
from runtime.capabilities.validation import validate_tool
from runtime.exceptions import ToolNotFoundError, ToolRegistrationError

if TYPE_CHECKING:
    from runtime.capabilities.tool import Tool
    from runtime.context import ApplicationContext

SOURCE = "tool_registry"


class ToolRegistry:
    """Stores and retrieves tools by their `tool_id`.

    Mirrors `ServiceRegistry`'s role as a simple, explicit lookup table,
    extended with the validation and event emission a capability
    registry additionally needs. Registration is an explicit method
    call — there is no discovery or magic; plugins and startup code
    register the tools they provide. Like `PluginRegistry`, mutating
    methods take the `ApplicationContext` as a parameter to reach the
    `EventBus` (the registry is built before the context is complete).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, application_context: ApplicationContext) -> None:
        """Register `tool` under its `tool_id`.

        Emits `ToolRegistered`.

        Raises:
            CapabilityValidationError: If `tool` fails structural validation.
            ToolRegistrationError: If `tool.tool_id` is already registered.
        """
        validate_tool(tool)
        if tool.tool_id in self._tools:
            raise ToolRegistrationError(f"Tool '{tool.tool_id}' is already registered.")
        self._tools[tool.tool_id] = tool
        application_context.events.emit(
            ToolRegistered(
                source=SOURCE, payload={"tool_id": tool.tool_id, "name": tool.name}
            )
        )

    def unregister(self, tool_id: str, application_context: ApplicationContext) -> None:
        """Remove the tool registered under `tool_id`.

        Emits `ToolUnregistered`.

        Raises:
            ToolNotFoundError: If `tool_id` is not registered.
        """
        tool = self.get(tool_id)
        del self._tools[tool_id]
        application_context.events.emit(
            ToolUnregistered(
                source=SOURCE, payload={"tool_id": tool_id, "name": tool.name}
            )
        )

    def get(self, tool_id: str) -> Tool:
        """Return the tool registered under `tool_id`.

        Raises:
            ToolNotFoundError: If `tool_id` is not registered.
        """
        try:
            return self._tools[tool_id]
        except KeyError:
            raise ToolNotFoundError(f"Tool '{tool_id}' is not registered.") from None

    def has(self, tool_id: str) -> bool:
        """Return True if a tool is registered under `tool_id`."""
        return tool_id in self._tools

    def list(self) -> list[Tool]:
        """Return a snapshot list of registered tools, in registration order."""
        return list(self._tools.values())
