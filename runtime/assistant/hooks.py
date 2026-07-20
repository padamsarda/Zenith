"""AssistantHook: interception points around request and tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.assistant.response import AssistantResponse
    from runtime.commands.result import CommandResult
    from runtime.context import ApplicationContext
    from runtime.providers.base import ToolCall


class AssistantHook:
    """Base class for hooks into the assistant pipeline.

    Hooks are how cross-cutting concerns — auditing, budgets, safety
    checks, user confirmation — attach to execution without the engine
    knowing about them. Every method is a no-op by default; subclasses
    override only the points they care about, and hooks are added by an
    explicit `AssistantEngine.add_hook` call, never discovered.

    The semantics differ deliberately between the two kinds of method:

    - `before_*` methods run before the guarded operation and may veto
      it by raising. A raise from `before_request` fails the request; a
      raise from `before_tool` blocks that tool call (recorded as a
      denial the provider can see). This is what distinguishes hooks
      from event listeners, which can only observe.
    - `after_*` methods are observational. A raise from one is logged
      and suppressed, exactly like a failing `EventBus` listener — the
      outcome it observed has already happened.

    Hooks complement the `PermissionPolicy`: the policy is the standing
    rule for what tools may run; hooks are arbitrary code around
    individual operations.
    """

    def before_request(
        self, request: AssistantRequest, application_context: ApplicationContext
    ) -> None:
        """Called before a request is served. Raise to reject the request."""

    def after_request(
        self,
        request: AssistantRequest,
        response: AssistantResponse,
        application_context: ApplicationContext,
    ) -> None:
        """Called after a request finishes, on every outcome. Observational."""

    def before_tool(
        self,
        request: AssistantRequest,
        call: ToolCall,
        application_context: ApplicationContext,
    ) -> None:
        """Called before a permitted tool call executes. Raise to block it."""

    def after_tool(
        self,
        request: AssistantRequest,
        call: ToolCall,
        result: CommandResult,
        application_context: ApplicationContext,
    ) -> None:
        """Called after a tool call executes, on every outcome. Observational."""
