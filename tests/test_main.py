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
from runtime.memory.sqlite.store import SQLiteMemoryStore
from runtime.providers.claude import API_KEY_ENV_VAR


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.main"))


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ApplicationContext:
    """Wire Zeni with credentials present and its database redirected to tmp_path.

    Redirecting `MEMORY_DB_PATH` matters: the real one lives under the
    user's home directory, and a test must never touch it.
    """
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(main, "MEMORY_DB_PATH", tmp_path / "memory.db")
    context = make_application_context()
    _wire_zeni(context, tmp_path)
    yield context
    if isinstance(context.memory, SQLiteMemoryStore):
        context.memory.close()


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


def test_memory_database_is_created(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "nested" / "memory.db"
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    monkeypatch.setattr(main, "MEMORY_DB_PATH", path)
    context = make_application_context()

    _wire_zeni(context, tmp_path)

    try:
        assert path.exists()
    finally:
        context.memory.close()
