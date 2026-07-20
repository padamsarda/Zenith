"""ToolCallRunner: executes one provider-requested tool call safely."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runtime.assistant.events import (
    ToolCallCompleted,
    ToolCallDenied,
    ToolCallFailed,
    ToolCallRequested,
)
from runtime.commands.command import Command
from runtime.conversation.message import Message, MessageRole
from runtime.exceptions import ToolNotFoundError

if TYPE_CHECKING:
    from runtime.assistant.hooks import AssistantHook
    from runtime.assistant.permissions import PermissionPolicy
    from runtime.assistant.request import AssistantRequest
    from runtime.context import ApplicationContext
    from runtime.providers.base import ToolCall

DEFAULT_LOGGER_NAME = "zenith.assistant"
SOURCE = "assistant_engine"


class ToolCallRunner:
    """Runs one tool call for the `AssistantEngine`.

    Resolves the tool, consults the `PermissionPolicy`, runs
    `before_tool` hooks, and executes the invocation as a `Command`
    through the `CommandExecutor` — the same validated, timed, logged,
    event-emitting path every other Zenith action takes. Every outcome
    — unknown tool, denial, veto, failure, success — is recorded as a
    TOOL message in the conversation so the provider sees it on its
    next turn; none of them fails the request. `run` never raises.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def run(
        self,
        request: AssistantRequest,
        call: ToolCall,
        application_context: ApplicationContext,
        *,
        policy: PermissionPolicy,
        hooks: tuple[AssistantHook, ...],
    ) -> None:
        """Execute `call` for `request` and record its outcome.

        Emits `ToolCallRequested` on entry, then exactly one of
        `ToolCallCompleted`, `ToolCallDenied`, or `ToolCallFailed`.
        """
        events = application_context.events
        payload = {
            "request_id": str(request.request_id),
            "call_id": str(call.call_id),
            "tool_id": call.tool_id,
        }
        events.emit(ToolCallRequested(source=SOURCE, payload=dict(payload)))

        try:
            tool = application_context.tools.get(call.tool_id)
        except ToolNotFoundError as exc:
            events.emit(ToolCallFailed(source=SOURCE, payload={**payload, "reason": str(exc)}))
            self._record(request, call, str(exc), application_context)
            return

        decision = policy.evaluate(request, call, tool)
        if not decision.allowed:
            reason = decision.reason or "Denied by the permission policy."
            events.emit(ToolCallDenied(source=SOURCE, payload={**payload, "reason": reason}))
            self._record(
                request, call, f"Tool '{call.tool_id}' was denied: {reason}", application_context
            )
            return

        for hook in hooks:
            try:
                hook.before_tool(request, call, application_context)
            except Exception as exc:
                events.emit(
                    ToolCallDenied(source=SOURCE, payload={**payload, "reason": str(exc)})
                )
                self._record(
                    request,
                    call,
                    f"Tool '{call.tool_id}' was blocked: {exc}",
                    application_context,
                )
                return

        command = Command(
            name=f"tool.{call.tool_id}",
            description=tool.description,
            metadata=dict(payload),
        )
        result = application_context.commands.execute(
            command,
            application_context,
            lambda context: tool.invoke(context, call.arguments),
        )
        if result.success:
            output = str(result.data) if result.data is not None else ""
            content = output if output.strip() else "(no output)"
            events.emit(
                ToolCallCompleted(
                    source=SOURCE,
                    payload={**payload, "duration_seconds": result.duration_seconds},
                )
            )
        else:
            content = f"Tool '{call.tool_id}' failed: {result.message}"
            events.emit(
                ToolCallFailed(source=SOURCE, payload={**payload, "reason": result.message})
            )
        self._record(request, call, content, application_context)

        for hook in hooks:
            try:
                hook.after_tool(request, call, result, application_context)
            except Exception:
                self._logger.warning("after_tool hook failed.", exc_info=True)

    def _record(
        self,
        request: AssistantRequest,
        call: ToolCall,
        content: str,
        application_context: ApplicationContext,
    ) -> None:
        """Append the call's outcome to the conversation as a TOOL message."""
        application_context.conversations.append(
            request.conversation_id,
            Message(
                role=MessageRole.TOOL,
                content=content,
                metadata={
                    "request_id": str(request.request_id),
                    "tool_id": call.tool_id,
                    "call_id": str(call.call_id),
                },
            ),
            application_context,
        )
