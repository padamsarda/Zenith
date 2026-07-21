"""Tests for ConfirmationHook."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.assistant.confirmation import ConfirmationHook
from runtime.assistant.request import AssistantRequest
from runtime.context import ApplicationContext
from runtime.exceptions import ToolCallVetoedError
from runtime.providers.base import ToolCall
from shared.utils.uuid_utils import generate_id


class RecordingConfirmer:
    """A fake `Confirmer` that records what it was asked and returns a fixed answer."""

    def __init__(self, *, answer: bool) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def __call__(self, description: str) -> bool:
        self.asked.append(description)
        return self.answer


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.confirmation"))


def make_request() -> AssistantRequest:
    return AssistantRequest(conversation_id=generate_id(), text="do something")


# --- what gets gated ----------------------------------------------------------------


def test_shell_call_is_always_gated() -> None:
    confirmer = RecordingConfirmer(answer=True)
    hook = ConfirmationHook(confirmer=confirmer)
    call = ToolCall(tool_id="shell", arguments={"command": "rm -rf /"})

    hook.before_tool(make_request(), call, make_application_context())

    assert confirmer.asked == ["run shell command 'rm -rf /'"]


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_destructive_filesystem_operations_are_gated(operation: str) -> None:
    confirmer = RecordingConfirmer(answer=True)
    hook = ConfirmationHook(confirmer=confirmer)
    call = ToolCall(tool_id="filesystem", arguments={"operation": operation, "path": "a.txt"})

    hook.before_tool(make_request(), call, make_application_context())

    assert confirmer.asked == [f"{operation} filesystem path 'a.txt'"]


@pytest.mark.parametrize("operation", ["read", "list", "mkdir", "exists"])
def test_non_destructive_filesystem_operations_are_not_gated(operation: str) -> None:
    confirmer = RecordingConfirmer(answer=False)
    hook = ConfirmationHook(confirmer=confirmer)
    call = ToolCall(tool_id="filesystem", arguments={"operation": operation, "path": "a.txt"})

    hook.before_tool(make_request(), call, make_application_context())

    assert confirmer.asked == []


@pytest.mark.parametrize("tool_id", ["app_launcher", "media_control", "git", "diff", "test_runner"])
def test_other_tools_are_not_gated(tool_id: str) -> None:
    confirmer = RecordingConfirmer(answer=False)
    hook = ConfirmationHook(confirmer=confirmer)
    call = ToolCall(tool_id=tool_id, arguments={})

    hook.before_tool(make_request(), call, make_application_context())

    assert confirmer.asked == []


# --- the decision ----------------------------------------------------------------


def test_approval_lets_the_call_proceed() -> None:
    hook = ConfirmationHook(confirmer=RecordingConfirmer(answer=True))
    call = ToolCall(tool_id="shell", arguments={"command": "ls"})

    assert hook.before_tool(make_request(), call, make_application_context()) is None


def test_decline_raises_tool_call_vetoed_error() -> None:
    hook = ConfirmationHook(confirmer=RecordingConfirmer(answer=False))
    call = ToolCall(tool_id="shell", arguments={"command": "ls"})

    with pytest.raises(ToolCallVetoedError):
        hook.before_tool(make_request(), call, make_application_context())
