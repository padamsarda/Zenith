"""Tests for main._wire_zeni, Zeni's composition root."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from configs.config import Config
from main import TOOL_IDS, _wire_zeni
from runtime.assistant.confirmation import ConfirmationHook
from runtime.assistant.permissions import AllowAllPolicy, ToolAllowlistPolicy
from runtime.context import ApplicationContext
from runtime.providers.claude import API_KEY_ENV_VAR


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.main"))


def test_without_api_key_nothing_is_registered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    app_context = make_application_context()

    _wire_zeni(app_context, tmp_path)

    assert app_context.assistant_providers.list() == []
    assert app_context.tools.list() == []
    assert isinstance(app_context.assistant.permission_policy, AllowAllPolicy)
    assert app_context.assistant.hooks == ()


def test_with_api_key_the_full_suite_is_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    app_context = make_application_context()

    _wire_zeni(app_context, tmp_path)

    assert app_context.assistant_providers.has("claude")
    for tool_id in TOOL_IDS:
        assert app_context.tools.has(tool_id), tool_id

    policy = app_context.assistant.permission_policy
    assert isinstance(policy, ToolAllowlistPolicy)

    hooks = app_context.assistant.hooks
    assert len(hooks) == 1
    assert isinstance(hooks[0], ConfirmationHook)


def test_registered_tool_ids_match_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-key")
    app_context = make_application_context()

    _wire_zeni(app_context, tmp_path)

    registered_ids = {tool.tool_id for tool in app_context.tools.list()}
    assert registered_ids == set(TOOL_IDS)
