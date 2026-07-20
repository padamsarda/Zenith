"""Tests for the AssistantHook base class."""

from __future__ import annotations

import logging

from configs.config import Config
from runtime.assistant.hooks import AssistantHook
from runtime.assistant.request import AssistantRequest
from runtime.assistant.response import AssistantResponse
from runtime.commands.result import CommandResult
from runtime.context import ApplicationContext
from runtime.providers.base import ToolCall
from shared.utils.uuid_utils import generate_id


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.hooks"))


def make_request() -> AssistantRequest:
    return AssistantRequest(conversation_id=generate_id(), text="hello")


def make_response(request: AssistantRequest) -> AssistantResponse:
    return AssistantResponse(
        success=True,
        text="hi",
        request_id=request.request_id,
        conversation_id=request.conversation_id,
        duration_seconds=0.1,
    )


def test_base_hook_is_instantiable() -> None:
    assert isinstance(AssistantHook(), AssistantHook)


def test_every_default_method_is_a_no_op() -> None:
    hook = AssistantHook()
    app_context = make_application_context()
    request = make_request()
    call = ToolCall(tool_id="clock")
    result = CommandResult(success=True, message="ok", duration_seconds=0.1)

    assert hook.before_request(request, app_context) is None
    assert hook.after_request(request, make_response(request), app_context) is None
    assert hook.before_tool(request, call, app_context) is None
    assert hook.after_tool(request, call, result, app_context) is None


def test_subclass_overrides_only_what_it_needs() -> None:
    seen: list[str] = []

    class BeforeOnlyHook(AssistantHook):
        def before_request(
            self, request: AssistantRequest, application_context: ApplicationContext
        ) -> None:
            seen.append("before_request")

    hook = BeforeOnlyHook()
    app_context = make_application_context()
    request = make_request()
    hook.before_request(request, app_context)
    hook.after_request(request, make_response(request), app_context)

    assert seen == ["before_request"]
