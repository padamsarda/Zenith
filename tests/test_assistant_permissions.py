"""Tests for the PermissionPolicy seam."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from runtime.assistant.permissions import (
    AllowAllPolicy,
    PermissionDecision,
    PermissionPolicy,
)
from runtime.assistant.request import AssistantRequest
from runtime.capabilities.tool import Tool
from runtime.commands.context import CommandContext
from runtime.providers.base import ToolCall
from shared.utils.uuid_utils import generate_id


class ClockTool(Tool):
    """A minimal concrete tool."""

    @property
    def tool_id(self) -> str:
        return "clock"

    @property
    def name(self) -> str:
        return "Clock"

    @property
    def description(self) -> str:
        return "Tells the time."

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return "12:00"


def test_policy_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        PermissionPolicy()  # type: ignore[abstract]


def test_allow_all_policy_allows() -> None:
    request = AssistantRequest(conversation_id=generate_id(), text="time?")

    decision = AllowAllPolicy().evaluate(request, ToolCall(tool_id="clock"), ClockTool())

    assert decision.allowed is True
    assert decision.reason is None


def test_decision_is_frozen() -> None:
    decision = PermissionDecision(allowed=False, reason="not allowed")

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.allowed = True  # type: ignore[misc]


def test_custom_policy_can_deny() -> None:
    class DenyClockPolicy(PermissionPolicy):
        def evaluate(
            self, request: AssistantRequest, call: ToolCall, tool: Tool
        ) -> PermissionDecision:
            if call.tool_id == "clock":
                return PermissionDecision(allowed=False, reason="clocks are off limits")
            return PermissionDecision(allowed=True)

    request = AssistantRequest(conversation_id=generate_id(), text="time?")

    decision = DenyClockPolicy().evaluate(request, ToolCall(tool_id="clock"), ClockTool())

    assert decision.allowed is False
    assert decision.reason == "clocks are off limits"
