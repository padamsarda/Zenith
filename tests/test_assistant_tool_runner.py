"""Tests for the ToolCallRunner."""

from __future__ import annotations

import logging
from typing import Any

from configs.config import Config
from runtime.assistant.events import (
    ToolCallCompleted,
    ToolCallDenied,
    ToolCallFailed,
    ToolCallRequested,
)
from runtime.assistant.hooks import AssistantHook
from runtime.assistant.permissions import (
    AllowAllPolicy,
    PermissionDecision,
    PermissionPolicy,
)
from runtime.assistant.request import AssistantRequest
from runtime.assistant.tool_runner import ToolCallRunner
from runtime.capabilities.tool import Tool
from runtime.commands.context import CommandContext
from runtime.commands.events import CommandCompleted
from runtime.commands.result import CommandResult
from runtime.context import ApplicationContext
from runtime.conversation.conversation import Conversation
from runtime.conversation.message import MessageRole
from runtime.providers.base import ToolCall
from shared.events.event import Event

ALL_TOOL_CALL_EVENT_TYPES = (
    ToolCallRequested,
    ToolCallDenied,
    ToolCallCompleted,
    ToolCallFailed,
)


class RecordingTool(Tool):
    """A tool that records invocations and returns a configurable result."""

    def __init__(self, result: Any = "12:00", error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.invocations: list[dict[str, Any]] = []

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
        self.invocations.append(arguments)
        if self._error is not None:
            raise self._error
        return self._result


class DenyAllPolicy(PermissionPolicy):
    """Denies every call with a fixed reason."""

    def evaluate(
        self, request: AssistantRequest, call: ToolCall, tool: Tool
    ) -> PermissionDecision:
        return PermissionDecision(allowed=False, reason="not today")


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.tool_runner"))


def make_request(app_context: ApplicationContext) -> tuple[AssistantRequest, Conversation]:
    conversation = app_context.conversations.create(app_context)
    request = AssistantRequest(conversation_id=conversation.conversation_id, text="time?")
    return request, conversation


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in ALL_TOOL_CALL_EVENT_TYPES:
        app_context.events.subscribe(event_type, received.append)
    return received


def run(
    app_context: ApplicationContext,
    request: AssistantRequest,
    call: ToolCall,
    policy: PermissionPolicy | None = None,
    hooks: tuple[AssistantHook, ...] = (),
) -> None:
    ToolCallRunner().run(
        request, call, app_context, policy=policy or AllowAllPolicy(), hooks=hooks
    )


def test_successful_call_records_the_result() -> None:
    app_context = make_application_context()
    tool = RecordingTool()
    app_context.tools.register(tool, app_context)
    request, conversation = make_request(app_context)
    call = ToolCall(tool_id="clock", arguments={"zone": "utc"})

    run(app_context, request, call)

    assert tool.invocations == [{"zone": "utc"}]
    (message,) = conversation.messages
    assert message.role is MessageRole.TOOL
    assert message.content == "12:00"
    assert message.metadata == {
        "request_id": str(request.request_id),
        "tool_id": "clock",
        "call_id": str(call.call_id),
    }


def test_successful_call_emits_requested_then_completed() -> None:
    app_context = make_application_context()
    app_context.tools.register(RecordingTool(), app_context)
    request, _ = make_request(app_context)
    received = subscribe_all(app_context)

    run(app_context, request, ToolCall(tool_id="clock"))

    assert [type(event) for event in received] == [ToolCallRequested, ToolCallCompleted]


def test_none_result_records_no_output_placeholder() -> None:
    app_context = make_application_context()
    app_context.tools.register(RecordingTool(result=None), app_context)
    request, conversation = make_request(app_context)

    run(app_context, request, ToolCall(tool_id="clock"))

    assert conversation.messages[0].content == "(no output)"


def test_unknown_tool_records_failure_without_raising() -> None:
    app_context = make_application_context()
    request, conversation = make_request(app_context)
    received = subscribe_all(app_context)

    run(app_context, request, ToolCall(tool_id="missing"))

    assert [type(event) for event in received] == [ToolCallRequested, ToolCallFailed]
    assert "missing" in conversation.messages[0].content


def test_denied_call_never_invokes_the_tool() -> None:
    app_context = make_application_context()
    tool = RecordingTool()
    app_context.tools.register(tool, app_context)
    request, conversation = make_request(app_context)
    received = subscribe_all(app_context)

    run(app_context, request, ToolCall(tool_id="clock"), policy=DenyAllPolicy())

    assert tool.invocations == []
    assert [type(event) for event in received] == [ToolCallRequested, ToolCallDenied]
    assert conversation.messages[0].content == "Tool 'clock' was denied: not today"


def test_before_tool_hook_veto_blocks_the_call() -> None:
    class VetoHook(AssistantHook):
        def before_tool(
            self,
            request: AssistantRequest,
            call: ToolCall,
            application_context: ApplicationContext,
        ) -> None:
            raise RuntimeError("vetoed")

    app_context = make_application_context()
    tool = RecordingTool()
    app_context.tools.register(tool, app_context)
    request, conversation = make_request(app_context)
    received = subscribe_all(app_context)

    run(app_context, request, ToolCall(tool_id="clock"), hooks=(VetoHook(),))

    assert tool.invocations == []
    assert [type(event) for event in received] == [ToolCallRequested, ToolCallDenied]
    assert conversation.messages[0].content == "Tool 'clock' was blocked: vetoed"


def test_tool_error_records_failure_without_raising() -> None:
    app_context = make_application_context()
    app_context.tools.register(RecordingTool(error=RuntimeError("boom")), app_context)
    request, conversation = make_request(app_context)
    received = subscribe_all(app_context)

    run(app_context, request, ToolCall(tool_id="clock"))

    assert [type(event) for event in received] == [ToolCallRequested, ToolCallFailed]
    assert conversation.messages[0].content == "Tool 'clock' failed: boom"


def test_after_tool_hook_sees_the_result() -> None:
    results: list[CommandResult] = []

    class ObservingHook(AssistantHook):
        def after_tool(
            self,
            request: AssistantRequest,
            call: ToolCall,
            result: CommandResult,
            application_context: ApplicationContext,
        ) -> None:
            results.append(result)

    app_context = make_application_context()
    app_context.tools.register(RecordingTool(), app_context)
    request, _ = make_request(app_context)

    run(app_context, request, ToolCall(tool_id="clock"), hooks=(ObservingHook(),))

    assert len(results) == 1
    assert results[0].success is True


def test_failing_after_tool_hook_is_suppressed() -> None:
    class FailingHook(AssistantHook):
        def after_tool(
            self,
            request: AssistantRequest,
            call: ToolCall,
            result: CommandResult,
            application_context: ApplicationContext,
        ) -> None:
            raise RuntimeError("observer bug")

    app_context = make_application_context()
    app_context.tools.register(RecordingTool(), app_context)
    request, conversation = make_request(app_context)

    run(app_context, request, ToolCall(tool_id="clock"), hooks=(FailingHook(),))

    assert conversation.messages[0].content == "12:00"


def test_call_executes_through_the_command_executor() -> None:
    app_context = make_application_context()
    app_context.tools.register(RecordingTool(), app_context)
    request, _ = make_request(app_context)
    completed: list[Event] = []
    app_context.events.subscribe(CommandCompleted, completed.append)

    run(app_context, request, ToolCall(tool_id="clock"))

    assert len(completed) == 1
