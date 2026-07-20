"""PermissionPolicy: the boundary deciding which tool calls may run."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
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


class ToolAllowlistPolicy(PermissionPolicy):
    """Permits only tool calls whose `tool_id` is on an explicit allowlist.

    The seam the roadmap anticipated: `AllowAllPolicy` is honest only
    while every registered tool is harmless. The moment a tool can
    genuinely act on the world — write a file, run a shell command,
    commit to a repository (`runtime.tools`, ADR 0016) — an integrator
    should replace the default with this policy (or a stricter one),
    naming exactly which tools a given deployment permits. A `tool_id`
    absent from the allowlist is denied, not merely unpermitted by
    omission.
    """

    def __init__(self, allowed_tool_ids: Iterable[str]) -> None:
        """Create a policy permitting only `allowed_tool_ids`.

        Args:
            allowed_tool_ids: The `tool_id`s this policy allows. A call
                for any other tool_id is denied.
        """
        self._allowed_tool_ids = frozenset(allowed_tool_ids)

    def evaluate(
        self, request: AssistantRequest, call: ToolCall, tool: Tool
    ) -> PermissionDecision:
        if call.tool_id in self._allowed_tool_ids:
            return PermissionDecision(allowed=True)
        return PermissionDecision(
            allowed=False, reason=f"Tool '{call.tool_id}' is not on the allowlist."
        )
