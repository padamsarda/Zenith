"""Tests for main._wire_zeni, Zeni's composition root."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import main
from configs.config import Config
from main import TOOL_IDS, _wire_zeni
from runtime.assistant.confirmation import ConfirmationHook
from runtime.assistant.memory_capture import MemoryCaptureHook
from runtime.assistant.permissions import AllowAllPolicy, ToolAllowlistPolicy
from runtime.context import ApplicationContext
from runtime.memory.in_memory_store import InMemoryMemoryStore
from runtime.memory.memory import Memory
from runtime.memory.sqlite.store import SQLiteMemoryStore
from runtime.providers.claude import API_KEY_ENV_VAR
from runtime.reflection.in_memory_store import InMemoryReflectionStore
from runtime.reflection.sqlite.store import SQLiteReflectionStore


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.main"))


def redirect_databases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every durable store at `tmp_path`.

    Load-bearing: the real paths live under the user's home directory,
    and a test must never touch them. Every database `_wire_zeni` opens
    has to be redirected here — one missed path silently writes to the
    user's real state.
    """
    monkeypatch.setattr(main, "MEMORY_DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(main, "REFLECTION_DB_PATH", tmp_path / "reflections.db")


def close_stores(context: ApplicationContext) -> None:
    """Close any durable stores the context holds."""
    if isinstance(context.memory, SQLiteMemoryStore):
        context.memory.close()
    if isinstance(context.reflections, SQLiteReflectionStore):
        context.reflections.close()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ApplicationContext:
    """Wire Zeni with credentials present and its databases redirected to tmp_path."""
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    redirect_databases(monkeypatch, tmp_path)
    context = make_application_context()
    _wire_zeni(context, tmp_path)
    yield context
    close_stores(context)


def test_without_api_key_nothing_is_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    context = make_application_context()

    _wire_zeni(context, tmp_path)

    assert context.assistant_providers.list() == []
    assert context.tools.list() == []
    assert isinstance(context.assistant.permission_policy, AllowAllPolicy)
    assert context.assistant.hooks == ()
    assert isinstance(context.memory, InMemoryMemoryStore)
    assert isinstance(context.reflections, InMemoryReflectionStore)


def test_with_api_key_the_full_suite_is_registered(wired: ApplicationContext) -> None:
    assert wired.assistant_providers.has("claude")
    for tool_id in TOOL_IDS:
        assert wired.tools.has(tool_id), tool_id

    assert isinstance(wired.assistant.permission_policy, ToolAllowlistPolicy)


def test_registered_tool_ids_match_the_allowlist(wired: ApplicationContext) -> None:
    assert {tool.tool_id for tool in wired.tools.list()} == set(TOOL_IDS)


def test_both_hooks_are_attached(wired: ApplicationContext) -> None:
    kinds = {type(hook) for hook in wired.assistant.hooks}

    assert kinds == {ConfirmationHook, MemoryCaptureHook}


def test_durable_memory_replaces_the_in_memory_default(wired: ApplicationContext) -> None:
    assert isinstance(wired.memory, SQLiteMemoryStore)


def test_databases_are_created(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(main, "MEMORY_DB_PATH", tmp_path / "nested" / "memory.db")
    monkeypatch.setattr(main, "REFLECTION_DB_PATH", tmp_path / "nested" / "reflections.db")
    context = make_application_context()

    _wire_zeni(context, tmp_path)

    try:
        assert (tmp_path / "nested" / "memory.db").exists()
        assert (tmp_path / "nested" / "reflections.db").exists()
    finally:
        close_stores(context)


def test_durable_reflection_store_replaces_the_default(wired: ApplicationContext) -> None:
    assert isinstance(wired.reflections, SQLiteReflectionStore)


def test_reflection_and_memory_use_separate_databases() -> None:
    # Keeping the derived layer out of the raw one's file is what makes
    # rebuilding reflections risk-free (ADR 0029).
    assert main.MEMORY_DB_PATH != main.REFLECTION_DB_PATH


def test_archiving_a_conversation_triggers_session_reflection(
    wired: ApplicationContext,
) -> None:
    # The session trigger is a bus subscription, so no interface needs to
    # know reflection exists.
    conversation = wired.conversations.create(wired, title="session")
    for index in range(4):
        wired.memory.remember(
            Memory(
                content=f"a substantive thing number {index}",
                metadata={"conversation_id": str(conversation.conversation_id)},
            ),
            wired,
        )

    # The real ClaudeProvider cannot reach the network with a fake key,
    # so reflection declines rather than producing anything — the
    # assertion is that archiving still succeeds and nothing propagates.
    wired.conversations.archive(conversation.conversation_id, wired)

    assert wired.conversations.get(conversation.conversation_id).state.name == "ARCHIVED"
