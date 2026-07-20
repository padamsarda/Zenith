"""PermissionPolicy: the boundary deciding which tool calls may run."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.capabilities.tool import Tool
    from runtime.providers.base import ToolCall


@dataclass(frozen=True)
class PermissionDecision:
    """The outcome of a permission check.

    `reason` explains a denial; it is recorded in the conversation so
    the provider (and any human reading the transcript) can see why the
    call did not run.
    """

    allowed: bool
    reason: str | None = None


class PermissionPolicy(ABC):
    """Decides whether one tool call may execute.

    This is the assistant pipeline's policy seam, the same shape as the
    Engineering Manager's `AssignmentPolicy` and `RetryPolicy`: the
    engine consults exactly one policy per tool call and enforces its
    decision, so replacing the class changes what is permitted without
    touching the engine. A denial is not an error — it is recorded in
    the conversation as the call's outcome and the request continues.
    """

    @abstractmethod
    def evaluate(
        self, request: AssistantRequest, call: ToolCall, tool: Tool
    ) -> PermissionDecision:
        """Return the decision for `call` against `tool` within `request`."""


class AllowAllPolicy(PermissionPolicy):
    """Permits every tool call.

    The default policy: with only built-in, deliberately harmless tools
    registered, there is nothing yet to guard. Real deployments replace
    this the moment a tool can act on the world in ways a user would
    want gated.
    """

    def evaluate(
        self, request: AssistantRequest, call: ToolCall, tool: Tool
    ) -> PermissionDecision:
        return PermissionDecision(allowed=True)
