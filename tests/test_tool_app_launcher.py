"""Tests for AppLauncherTool."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.app_launcher import AppLaunchResult, AppLauncherTool


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.app_launcher"))
    return CommandContext(application_context=app_context, command_id=uuid4())


class RecordingLauncher:
    """A fake `Launcher` that records what it was asked to launch."""

    def __init__(self, *, fail_with: OSError | None = None) -> None:
        self.calls: list[str] = []
        self._fail_with = fail_with

    def __call__(self, command: str) -> None:
        self.calls.append(command)
        if self._fail_with is not None:
            raise self._fail_with


# --- identity ----------------------------------------------------------------


def test_tool_identity() -> None:
    tool = AppLauncherTool(launcher=RecordingLauncher())

    assert tool.tool_id == "app_launcher"
    assert tool.name == "App Launcher"
    assert {parameter.name for parameter in tool.parameters} == {"app_name"}


# --- resolution ----------------------------------------------------------------


def test_catalog_entry_resolves_to_its_command() -> None:
    launcher = RecordingLauncher()
    tool = AppLauncherTool(launcher=launcher)

    result = tool.invoke(make_context(), {"app_name": "VS Code"})

    assert launcher.calls == ["code"]
    assert result == AppLaunchResult(app_name="VS Code", command="code", message="Opened VS Code.")
    assert str(result) == "Opened VS Code."


def test_catalog_lookup_is_case_and_whitespace_insensitive() -> None:
    launcher = RecordingLauncher()
    tool = AppLauncherTool(launcher=launcher)

    tool.invoke(make_context(), {"app_name": "  Spotify  "})

    assert launcher.calls == ["spotify"]


def test_unknown_name_passes_through_unchanged() -> None:
    launcher = RecordingLauncher()
    tool = AppLauncherTool(launcher=launcher)

    result = tool.invoke(make_context(), {"app_name": "obscure-tool"})

    assert launcher.calls == ["obscure-tool"]
    assert result.command == "obscure-tool"


def test_custom_catalog_overrides_default_entry() -> None:
    launcher = RecordingLauncher()
    tool = AppLauncherTool({"spotify": "C:/Apps/Spotify/Spotify.exe"}, launcher=launcher)

    tool.invoke(make_context(), {"app_name": "spotify"})

    assert launcher.calls == ["C:/Apps/Spotify/Spotify.exe"]


def test_custom_catalog_leaves_other_defaults_intact() -> None:
    launcher = RecordingLauncher()
    tool = AppLauncherTool({"kicad": "C:/Apps/KiCad/kicad.exe"}, launcher=launcher)

    tool.invoke(make_context(), {"app_name": "chrome"})

    assert launcher.calls == ["chrome"]


# --- failures ----------------------------------------------------------------


def test_missing_app_name_raises() -> None:
    tool = AppLauncherTool(launcher=RecordingLauncher())

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {})


def test_launcher_failure_becomes_tool_execution_error() -> None:
    launcher = RecordingLauncher(fail_with=OSError("not found"))
    tool = AppLauncherTool(launcher=launcher)

    with pytest.raises(ToolExecutionError, match="not found"):
        tool.invoke(make_context(), {"app_name": "spotify"})
