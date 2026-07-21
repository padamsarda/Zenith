"""Tests for MemoryCaptureHook."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.assistant.memory_capture import MAX_CAPTURED_LENGTH, MemoryCaptureHook
from runtime.assistant.request import AssistantRequest
from runtime.assistant.response import AssistantResponse
from runtime.context import ApplicationContext
from runtime.memory.memory import MAX_IMPORTANCE, MemoryKind
from runtime.memory.store import MemoryStore
from shared.utils.uuid_utils import generate_id


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.capture"))


def make_request(text: str) -> AssistantRequest:
    return AssistantRequest(conversation_id=generate_id(), text=text)


def make_response(request: AssistantRequest, *, success: bool = True) -> AssistantResponse:
    return AssistantResponse(
        success=success,
        text="ok",
        request_id=request.request_id,
        conversation_id=request.conversation_id,
        duration_seconds=0.1,
    )


def capture(text: str, *, success: bool = True) -> ApplicationContext:
    context = make_context()
    request = make_request(text)
    MemoryCaptureHook().after_request(request, make_response(request, success=success), context)
    return context


# --- what gets captured ----------------------------------------------------------------


def test_substantive_statement_is_captured() -> None:
    context = capture("The CubeSat battery is an 18650 lithium pack")

    stored = context.memory.list()
    assert len(stored) == 1
    assert stored[0].content == "The CubeSat battery is an 18650 lithium pack"
    assert stored[0].source == "conversation"


@pytest.mark.parametrize(
    "text", ["open spotify", "pause the music", "turn up the volume", "thanks"]
)
def test_trivial_commands_are_not_captured(text: str) -> None:
    assert capture(text).memory.list() == []


def test_failed_request_is_not_captured() -> None:
    # The exchange did not happen as intended; recording it would record
    # a misunderstanding as something Zeni knows.
    context = capture("The CubeSat battery is lithium", success=False)

    assert context.memory.list() == []


# --- how it is captured ----------------------------------------------------------------


def test_explicit_request_is_pinned_and_maximally_important() -> None:
    context = capture("remember that my student ID is f20250775")

    stored = context.memory.list()[0]
    assert stored.pinned is True
    assert stored.importance == MAX_IMPORTANCE


def test_ordinary_statement_is_not_pinned() -> None:
    context = capture("The solar panel produces 6 watts")

    assert context.memory.list()[0].pinned is False


def test_kind_is_inferred() -> None:
    context = capture("we decided to use an MPPT charge controller")

    assert context.memory.list()[0].kind is MemoryKind.DECISION


def test_conversation_id_is_recorded_in_metadata() -> None:
    context = make_context()
    request = make_request("The CubeSat battery is lithium")

    MemoryCaptureHook().after_request(request, make_response(request), context)

    stored = context.memory.list()[0]
    assert stored.metadata["conversation_id"] == str(request.conversation_id)


def test_overlong_text_is_truncated() -> None:
    context = capture("The battery specification is " + "x" * 2000)

    stored = context.memory.list()[0]
    assert len(stored.content) <= MAX_CAPTURED_LENGTH + 1
    assert stored.content.endswith("…")


# --- failure handling ----------------------------------------------------------------


def test_a_failing_store_does_not_propagate() -> None:
    # after_request is observational: a memory failure must never reach
    # the user's already-completed request.
    class BrokenStore(MemoryStore):
        def remember(self, memory, application_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def get(self, memory_id): ...  # type: ignore[no-untyped-def]
        def has(self, memory_id): ...  # type: ignore[no-untyped-def]
        def forget(self, memory_id, application_context): ...  # type: ignore[no-untyped-def]
        def search(self, query, *, window=None, limit=50): ...  # type: ignore[no-untyped-def]
        def touch(self, memories, application_context): ...  # type: ignore[no-untyped-def]
        def list(self): ...  # type: ignore[no-untyped-def]

    context = make_context()
    context.memory = BrokenStore()
    request = make_request("The CubeSat battery is lithium")

    MemoryCaptureHook().after_request(request, make_response(request), context)
