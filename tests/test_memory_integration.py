"""End-to-end tests for memory through the real assistant pipeline.

The unit tests cover each piece; these cover the thing the user actually
experiences — say something, then ask about it later and have Zeni
already know, with no tool call and no prompting. Everything here runs
through the genuine `AssistantEngine`, so a regression in the assembler,
the hook wiring, or the store surfaces here rather than in production.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from configs.config import Config
from runtime.assistant.memory_capture import MemoryCaptureHook
from runtime.assistant.request import AssistantRequest
from runtime.context import ApplicationContext
from runtime.memory.memory import Memory
from runtime.memory.sqlite.store import SQLiteMemoryStore
from runtime.providers.base import AssistantTurn
from runtime.providers.scripted import ScriptedProvider
from shared.utils.time_utils import utc_now


def make_context() -> ApplicationContext:
    context = ApplicationContext(
        config=Config(assistant_provider="scripted"),
        logger=logging.getLogger("test.memory_integration"),
    )
    context.assistant.add_hook(MemoryCaptureHook())
    return context


def install_provider(context: ApplicationContext, replies: list[str]) -> ScriptedProvider:
    provider = ScriptedProvider(turns=[AssistantTurn(text=reply) for reply in replies])
    context.assistant_providers.register(provider)
    return provider


def say(context: ApplicationContext, conversation_id, text: str) -> None:
    context.assistant.handle(
        AssistantRequest(conversation_id=conversation_id, text=text), context
    )


def test_a_stated_fact_is_remembered_and_recalled_without_a_tool_call() -> None:
    context = make_context()
    provider = install_provider(context, ["Noted.", "It is an 18650 lithium pack."])
    conversation = context.conversations.create(context, title="session")

    say(context, conversation.conversation_id, "The CubeSat battery is an 18650 lithium pack")
    say(context, conversation.conversation_id, "what battery does the cubesat use")

    # The memory reached the second turn's brief automatically — no
    # `memory` tool is even registered here.
    second_brief = provider.briefs[-1]
    assert second_brief.instructions is not None
    assert "18650 lithium pack" in second_brief.instructions


def test_the_first_turn_has_no_memories_to_recall() -> None:
    context = make_context()
    provider = install_provider(context, ["Noted."])
    conversation = context.conversations.create(context, title="session")

    say(context, conversation.conversation_id, "The CubeSat battery is an 18650 lithium pack")

    assert provider.briefs[0].instructions is None


def test_memory_crosses_conversation_boundaries() -> None:
    # The real test of long-term memory: a *new* conversation still knows.
    context = make_context()
    provider = install_provider(context, ["Noted.", "Yes, MPPT."])
    first = context.conversations.create(context, title="monday")
    say(context, first.conversation_id, "We decided to use an MPPT charge controller")

    second = context.conversations.create(context, title="tuesday")
    say(context, second.conversation_id, "what charge controller did we choose")

    assert "MPPT charge controller" in provider.briefs[-1].instructions


def test_device_commands_never_enter_memory() -> None:
    context = make_context()
    install_provider(context, ["Opened Spotify.", "Paused."])
    conversation = context.conversations.create(context, title="session")

    say(context, conversation.conversation_id, "open spotify")
    say(context, conversation.conversation_id, "pause the music")

    assert context.memory.list() == []


def test_a_time_scoped_question_recalls_that_day() -> None:
    context = make_context()
    provider = install_provider(context, ["You worked on the power budget."])
    now = utc_now()
    for content, days_ago in (
        ("Worked through the power budget spreadsheet", 1),
        ("Reviewed the antenna deployment sequence", 30),
    ):
        moment = now - timedelta(days=days_ago)
        context.memory.remember(
            Memory(
                content=content,
                occurred_at=moment,
                created_at=moment,
                last_accessed_at=moment,
            ),
            context,
        )

    conversation = context.conversations.create(context, title="session")
    say(context, conversation.conversation_id, "what was I working on yesterday")

    instructions = provider.briefs[-1].instructions
    assert instructions is not None
    assert "power budget" in instructions
    assert "antenna deployment" not in instructions


def test_recalled_memories_carry_how_long_ago_they_were() -> None:
    context = make_context()
    provider = install_provider(context, ["Noted."])
    moment = utc_now() - timedelta(days=1)
    context.memory.remember(
        Memory(
            content="We chose 18650 cells",
            occurred_at=moment,
            created_at=moment,
            last_accessed_at=moment,
        ),
        context,
    )

    conversation = context.conversations.create(context, title="session")
    say(context, conversation.conversation_id, "which cells did we choose")

    assert "yesterday" in provider.briefs[-1].instructions


def test_repeating_yourself_does_not_fill_memory_with_duplicates() -> None:
    # The failure consolidation exists to prevent: over daily use, the
    # same fact stated repeatedly would otherwise crowd out everything
    # else in the brief.
    context = make_context()
    install_provider(context, ["Noted."] * 4)
    conversation = context.conversations.create(context, title="session")

    for _ in range(4):
        say(context, conversation.conversation_id, "The CubeSat battery is an 18650 lithium pack")

    stored = context.memory.list()
    assert len(stored) == 1
    assert stored[0].importance > 5  # reinforced each time it was repeated


def test_correcting_yourself_replaces_the_old_fact_in_the_brief() -> None:
    context = make_context()
    provider = install_provider(context, ["Noted.", "Understood.", "It is LiFePO4."])
    conversation = context.conversations.create(context, title="session")

    say(context, conversation.conversation_id, "The CubeSat battery is an 18650 lithium pack")
    say(context, conversation.conversation_id, "actually the CubeSat battery is LiFePO4 now")
    say(context, conversation.conversation_id, "what battery does the cubesat use")

    instructions = provider.briefs[-1].instructions
    assert instructions is not None
    assert "LiFePO4" in instructions
    assert "18650" not in instructions


def test_memory_survives_a_restart_with_the_durable_store(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"

    first = make_context()
    first.memory = SQLiteMemoryStore(path)
    install_provider(first, ["Noted."])
    conversation = first.conversations.create(first, title="before")
    say(first, conversation.conversation_id, "My student ID is f20250775")
    first.memory.close()

    # A brand new context, as after a restart: only the database persists.
    second = make_context()
    second.memory = SQLiteMemoryStore(path)
    provider = install_provider(second, ["It is f20250775."])
    try:
        fresh = second.conversations.create(second, title="after")
        say(second, fresh.conversation_id, "what is my student ID")

        assert "f20250775" in provider.briefs[-1].instructions
    finally:
        second.memory.close()


def test_a_broken_memory_store_does_not_break_the_assistant() -> None:
    context = make_context()
    provider = install_provider(context, ["Still working."])

    class BrokenStore(SQLiteMemoryStore):
        def __init__(self) -> None:  # deliberately not calling super
            pass

        def search(self, query, *, window=None, limit=50):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def remember(self, memory, application_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    context.memory = BrokenStore()
    conversation = context.conversations.create(context, title="session")

    response = context.assistant.handle(
        AssistantRequest(conversation_id=conversation.conversation_id, text="hello there friend"),
        context,
    )

    assert response.success is True
    assert provider.briefs[-1].instructions is None
