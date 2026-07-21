"""Tests for AppControlTool."""

from __future__ import annotations

import logging
import sys
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.app_control import (
    AppControlResult,
    AppControlTool,
    default_process_closer,
    default_window_activator,
    default_window_lister,
)


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.app_control"))
    return CommandContext(application_context=app_context, command_id=uuid4())


class FakeWindows:
    """Fakes window listing/activation over a fixed, in-memory window list."""

    def __init__(self, titles: tuple[str, ...] = ()) -> None:
        self.titles = titles
        self.activation_requests: list[str] = []

    def lister(self) -> tuple[str, ...]:
        return self.titles

    def activator(self, title_substring: str) -> bool:
        self.activation_requests.append(title_substring)
        return any(title_substring.lower() in title.lower() for title in self.titles)


class RecordingCloser:
    def __init__(self, *, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls: list[str] = []

    def __call__(self, image_name: str) -> bool:
        self.calls.append(image_name)
        return self.succeeds


def make_tool(
    close_catalog: dict[str, str] | None = None,
    *,
    windows: FakeWindows | None = None,
    closer: RecordingCloser | None = None,
) -> AppControlTool:
    windows = windows or FakeWindows()
    closer = closer or RecordingCloser()
    return AppControlTool(
        close_catalog,
        window_lister=windows.lister,
        window_activator=windows.activator,
        process_closer=closer,
    )


# --- identity ----------------------------------------------------------------


def test_tool_identity() -> None:
    tool = make_tool()

    assert tool.tool_id == "app_control"
    assert tool.name == "App Control"
    assert {parameter.name for parameter in tool.parameters} == {"operation", "app_name"}


# --- list ----------------------------------------------------------------


def test_list_returns_window_titles() -> None:
    windows = FakeWindows(titles=("Spotify", "main.py - Visual Studio Code"))
    tool = make_tool(windows=windows)

    result = tool.invoke(make_context(), {"operation": "list"})

    assert result == AppControlResult(
        operation="list",
        message="2 open windows.",
        windows=("Spotify", "main.py - Visual Studio Code"),
    )
    assert "Spotify" in str(result)


def test_list_with_no_windows() -> None:
    tool = make_tool(windows=FakeWindows(titles=()))

    result = tool.invoke(make_context(), {"operation": "list"})

    assert result.message == "0 open windows."
    assert str(result) == "(no visible windows)"


# --- switch ----------------------------------------------------------------


def test_switch_activates_a_matching_window() -> None:
    windows = FakeWindows(titles=("Spotify Premium",))
    tool = make_tool(windows=windows)

    result = tool.invoke(make_context(), {"operation": "switch", "app_name": "spotify"})

    assert windows.activation_requests == ["spotify"]
    assert result == AppControlResult(operation="switch", message="Switched to spotify.")


def test_switch_with_no_match_raises() -> None:
    tool = make_tool(windows=FakeWindows(titles=("Notepad",)))

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"operation": "switch", "app_name": "spotify"})


def test_switch_without_app_name_raises() -> None:
    tool = make_tool()

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"operation": "switch"})


# --- close ----------------------------------------------------------------


def test_close_uses_catalog_image_name() -> None:
    closer = RecordingCloser(succeeds=True)
    tool = make_tool(closer=closer)

    result = tool.invoke(make_context(), {"operation": "close", "app_name": "Spotify"})

    assert closer.calls == ["Spotify.exe"]
    assert result == AppControlResult(operation="close", message="Closed Spotify.")


def test_close_falls_back_to_name_dot_exe() -> None:
    closer = RecordingCloser(succeeds=True)
    tool = make_tool(closer=closer)

    tool.invoke(make_context(), {"operation": "close", "app_name": "obscure-tool"})

    assert closer.calls == ["obscure-tool.exe"]


def test_close_custom_catalog_overrides_default() -> None:
    closer = RecordingCloser(succeeds=True)
    tool = make_tool({"spotify": "spotify-x64.exe"}, closer=closer)

    tool.invoke(make_context(), {"operation": "close", "app_name": "spotify"})

    assert closer.calls == ["spotify-x64.exe"]


def test_close_failure_raises() -> None:
    tool = make_tool(closer=RecordingCloser(succeeds=False))

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"operation": "close", "app_name": "spotify"})


def test_close_without_app_name_raises() -> None:
    tool = make_tool()

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"operation": "close"})


# --- unknown operation ----------------------------------------------------------------


def test_unknown_operation_raises() -> None:
    tool = make_tool()

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"operation": "minimize"})


# --- default implementations off Windows ----------------------------------------------------------------


def _skip_on_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("this platform can act; nothing to assert")


def test_default_window_lister_off_windows_fails_loudly() -> None:
    _skip_on_windows()

    with pytest.raises(ToolExecutionError, match="Windows"):
        default_window_lister()


def test_default_window_activator_off_windows_fails_loudly() -> None:
    _skip_on_windows()

    with pytest.raises(ToolExecutionError, match="Windows"):
        default_window_activator("anything")


def test_default_process_closer_off_windows_fails_loudly() -> None:
    _skip_on_windows()

    with pytest.raises(ToolExecutionError, match="Windows"):
        default_process_closer("anything.exe")
