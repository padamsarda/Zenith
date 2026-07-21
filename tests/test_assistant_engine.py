"""Tests for the AssistantEngine."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

import pytest

from configs.config import Config
from runtime.assistant.events import (
    RequestCompleted,
    RequestFailed,
    RequestReceived,
    ToolCallDenied,
)
from runtime.assistant.hooks import AssistantHook
from runtime.assistant.permissions import (
    AllowAllPolicy,
    PermissionDecision,
    PermissionPolicy,
)
from runtime.assistant.request import AssistantRequest
from runtime.assistant.response import AssistantResponse
from runtime.assistant.status import RequestStatus
from runtime.capabilities.tool import Tool
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.conversation.conversation import Conversation
from runtime.conversation.message import MessageRole
from runtime.conversation.sqlite.store import SQLiteConversationStore
from runtime.providers.base import AssistantTurn, ToolCall
from runtime.providers.scripted import ScriptedProvider
from shared.events.event import Event
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


def make_application_context(config: Config | None = None) -> ApplicationContext:
    return ApplicationContext(
        config=config or Config(assistant_provider="scripted"),
        logger=logging.getLogger("test.assistant_engine"),
    )


def make_conversation(app_context: ApplicationContext) -> Conversation:
    return app_context.conversations.create(app_context)


def make_request(
    conversation: Conversation, metadata: dict[str, Any] | None = None, text: str = "hello"
) -> AssistantRequest:
    return AssistantRequest(
        conversation_id=conversation.conversation_id, text=text, metadata=metadata or {}
    )


def install_scripted(
    app_context: ApplicationContext, turns: list[AssistantTurn]
) -> ScriptedProvider:
    provider = ScriptedProvider(turns)
    app_context.assistant_providers.register(provider)
    return provider


def subscribe_request_events(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in (RequestReceived, RequestCompleted, RequestFailed):
        app_context.events.subscribe(event_type, received.append)
    return received


def roles(conversation: Conversation) -> list[MessageRole]:
    return [message.role for message in conversation.messages]


# --- completion ---------------------------------------------------------


def test_text_only_turn_completes_the_request() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi there")])
    conversation = make_conversation(app_context)
    request = make_request(conversation)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is True
    assert response.text == "hi there"
    assert response.turns == 1
    assert request.status is RequestStatus.COMPLETED
    assert roles(conversation) == [MessageRole.USER, MessageRole.ASSISTANT]


def test_completion_emits_received_then_completed() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    conversation = make_conversation(app_context)
    received = subscribe_request_events(app_context)

    app_context.assistant.handle(make_request(conversation), app_context)

    assert [type(event) for event in received] == [RequestReceived, RequestCompleted]
    assert received[1].payload["turns"] == 1


def test_tool_loop_runs_tools_then_finishes() -> None:
    app_context = make_application_context()
    app_context.tools.register(ClockTool(), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),)),
            AssistantTurn(text="It is 12:00."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert response.text == "It is 12:00."
    assert response.turns == 2
    assert roles(conversation) == [MessageRole.USER, MessageRole.TOOL, MessageRole.ASSISTANT]
    assert conversation.messages[1].content == "12:00"


def test_turn_with_text_and_tools_records_both() -> None:
    app_context = make_application_context()
    app_context.tools.register(ClockTool(), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(text="Checking...", tool_calls=(ToolCall(tool_id="clock"),)),
            AssistantTurn(text="Done."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert roles(conversation) == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]


def test_second_turn_brief_includes_the_tool_result() -> None:
    app_context = make_application_context()
    app_context.tools.register(ClockTool(), app_context)
    provider = install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),)),
            AssistantTurn(text="Done."),
        ],
    )
    conversation = make_conversation(app_context)

    app_context.assistant.handle(make_request(conversation), app_context)

    second_brief = provider.briefs[1]
    assert [message.role for message in second_brief.messages] == [
        MessageRole.USER,
        MessageRole.TOOL,
    ]


# --- conversation stores that reconstruct on every get() ----------------
#
# InMemoryConversationStore.get() returns the same live object every
# call, so the engine would still see appended messages even if it held
# a `conversation` reference across a whole request by mistake.
# SQLiteConversationStore.get() rebuilds a fresh Conversation from
# storage each call, which is the real pressure test of whether the
# engine actually re-reads durable state per turn (ADR 0010) rather than
# relying on that in-memory implementation detail.


def test_second_turn_brief_includes_the_tool_result_with_a_reconstructing_store(
    tmp_path: Path,
) -> None:
    app_context = make_application_context()
    app_context.conversations = SQLiteConversationStore(tmp_path / "conversations.db")
    app_context.tools.register(ClockTool(), app_context)
    provider = install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),)),
            AssistantTurn(text="Done."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert response.text == "Done."
    second_brief = provider.briefs[1]
    assert [message.role for message in second_brief.messages] == [
        MessageRole.USER,
        MessageRole.TOOL,
    ]
    app_context.conversations.close()


# --- provider resolution ------------------------------------------------


def test_request_metadata_overrides_the_configured_provider() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [])
    named = ScriptedProvider([AssistantTurn(text="from named")], provider_id="named")
    app_context.assistant_providers.register(named)
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"provider": "named"})

    response = app_context.assistant.handle(request, app_context)

    assert response.success is True
    assert response.text == "from named"


def test_unknown_provider_fails_the_request() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)
    request = make_request(conversation)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert request.status is RequestStatus.FAILED
    assert roles(conversation) == []


# --- failures -----------------------------------------------------------


def test_blank_request_text_fails_before_any_message() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    conversation = make_conversation(app_context)
    request = make_request(conversation, text="   ")
    received = subscribe_request_events(app_context)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert request.status is RequestStatus.FAILED
    assert roles(conversation) == []
    assert [type(event) for event in received] == [RequestReceived, RequestFailed]


def test_unknown_conversation_fails_the_request() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    request = AssistantRequest(conversation_id=generate_id(), text="hello")

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert response.exception is not None


def test_provider_failure_fails_the_request() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [])
    conversation = make_conversation(app_context)
    request = make_request(conversation)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert request.status is RequestStatus.FAILED
    assert response.turns == 1


def test_unexpected_provider_exception_is_contained() -> None:
    class ExplodingProvider(ScriptedProvider):
        def generate_turn(self, brief: Any) -> AssistantTurn:
            raise RuntimeError("kaboom")

    app_context = make_application_context()
    app_context.assistant_providers.register(ExplodingProvider())
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is False
    assert "raised unexpectedly" in response.text


def test_empty_turn_fails_the_request() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn()])
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is False


def test_exhausting_max_turns_fails_the_request() -> None:
    config = Config(assistant_provider="scripted", assistant_max_turns=1)
    app_context = make_application_context(config)
    app_context.tools.register(ClockTool(), app_context)
    install_scripted(
        app_context, [AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),))]
    )
    conversation = make_conversation(app_context)
    request = make_request(conversation)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert response.text == "No final reply after 1 turns."
    assert request.status is RequestStatus.FAILED


# --- hooks and permissions ----------------------------------------------


def test_before_request_hook_veto_rejects_the_request() -> None:
    class VetoHook(AssistantHook):
        def before_request(
            self, request: AssistantRequest, application_context: ApplicationContext
        ) -> None:
            raise RuntimeError("not now")

    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    app_context.assistant.add_hook(VetoHook())
    conversation = make_conversation(app_context)
    request = make_request(conversation)

    response = app_context.assistant.handle(request, app_context)

    assert response.success is False
    assert "not now" in response.text
    assert request.status is RequestStatus.FAILED
    assert roles(conversation) == []


def test_after_request_hook_runs_on_success_and_failure() -> None:
    outcomes: list[bool] = []

    class ObservingHook(AssistantHook):
        def after_request(
            self,
            request: AssistantRequest,
            response: AssistantResponse,
            application_context: ApplicationContext,
        ) -> None:
            outcomes.append(response.success)

    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    app_context.assistant.add_hook(ObservingHook())
    conversation = make_conversation(app_context)
    app_context.assistant.handle(make_request(conversation), app_context)
    app_context.assistant.handle(make_request(conversation, text="  "), app_context)

    assert outcomes == [True, False]


def test_failing_after_request_hook_is_suppressed() -> None:
    class FailingHook(AssistantHook):
        def after_request(
            self,
            request: AssistantRequest,
            response: AssistantResponse,
            application_context: ApplicationContext,
        ) -> None:
            raise RuntimeError("observer bug")

    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    app_context.assistant.add_hook(FailingHook())
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True


def test_permission_policy_denial_is_recorded_not_fatal() -> None:
    class DenyAll(PermissionPolicy):
        def evaluate(
            self, request: AssistantRequest, call: ToolCall, tool: Tool
        ) -> PermissionDecision:
            return PermissionDecision(allowed=False, reason="locked down")

    app_context = make_application_context()
    app_context.tools.register(ClockTool(), app_context)
    app_context.assistant.set_permission_policy(DenyAll())
    install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),)),
            AssistantTurn(text="Understood."),
        ],
    )
    conversation = make_conversation(app_context)
    denied: list[Event] = []
    app_context.events.subscribe(ToolCallDenied, denied.append)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert len(denied) == 1
    assert "locked down" in conversation.messages[1].content


def test_default_policy_allows_everything() -> None:
    app_context = make_application_context()

    assert isinstance(app_context.assistant.permission_policy, AllowAllPolicy)


# --- response shape -----------------------------------------------------


def test_response_is_frozen() -> None:
    app_context = make_application_context()
    install_scripted(app_context, [AssistantTurn(text="hi")])
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    with pytest.raises(dataclasses.FrozenInstanceError):
        response.text = "changed"  # type: ignore[misc]
