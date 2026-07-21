"""AppControlTool: lists, focuses, and closes already-running applications."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import optional_str, require_str

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.app_control"
OPERATIONS = ("list", "switch", "close")

# `close` needs an exact OS process image name, unlike `AppLauncherTool`'s
# catalog (ADR 0024), which just needs something the OS can resolve by
# name. A name absent here falls back to "<name>.exe" — right often
# enough on Windows to be worth trying before giving up.
DEFAULT_CLOSE_CATALOG: Mapping[str, str] = {
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "code": "Code.exe",
    "spotify": "Spotify.exe",
    "chrome": "chrome.exe",
    "browser": "chrome.exe",
    "notion": "Notion.exe",
    "notepad": "notepad.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
}

WindowLister = Callable[[], tuple[str, ...]]
WindowActivator = Callable[[str], bool]
ProcessCloser = Callable[[str], bool]


def default_window_lister() -> tuple[str, ...]:
    """Return the titles of every visible top-level window.

    Raises:
        ToolExecutionError: Off Windows, where there is no window
            manager this can enumerate.
    """
    if sys.platform != "win32":
        raise ToolExecutionError("Listing windows requires Windows.")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _collect(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
        return True

    user32.EnumWindows(_collect, 0)
    return tuple(titles)


def default_window_activator(title_substring: str) -> bool:
    """Bring the first visible window whose title contains `title_substring` forward.

    Case-insensitive substring match. Windows itself may still refuse to
    hand over the foreground to a background process depending on what
    currently has focus — `SetForegroundWindow` is a request, not a
    guarantee, and this does not attempt to work around that OS policy.

    Raises:
        ToolExecutionError: Off Windows.

    Returns:
        Whether a matching window was found (not necessarily that it
        ended up in the foreground, per the caveat above).
    """
    if sys.platform != "win32":
        raise ToolExecutionError("Switching windows requires Windows.")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    needle = title_substring.lower()
    match = ctypes.c_void_p(0)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _find(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if needle in buffer.value.lower():
                    match.value = hwnd
                    return False
        return True

    user32.EnumWindows(_find, 0)
    if not match.value:
        return False
    user32.SetForegroundWindow(match)
    return True


def default_process_closer(image_name: str) -> bool:
    """Force-terminate every process running as `image_name` (e.g. `"Spotify.exe"`).

    Raises:
        ToolExecutionError: Off Windows, where `taskkill` does not exist.
    """
    if sys.platform != "win32":
        raise ToolExecutionError("Closing applications requires Windows.")
    result = subprocess.run(
        ["taskkill", "/IM", image_name, "/F"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@dataclass(frozen=True)
class AppControlResult:
    """The structured outcome of one app-control operation."""

    operation: str
    message: str
    windows: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.operation == "list":
            return "\n".join(self.windows) if self.windows else "(no visible windows)"
        return self.message


class AppControlTool(Tool):
    """Manages applications that are already running: list, switch, close.

    The complement of `AppLauncherTool` (ADR 0024), which only ever
    starts something new. `close` force-terminates a process — unlike
    everything else in the desktop-control suite, it can genuinely lose
    unsaved work, so it is one of the calls `ConfirmationHook`
    (`runtime.assistant.confirmation`, ADR 0025) asks about before it
    runs. `list` and `switch` are read-only/reversible and stay
    unconfirmed.
    """

    def __init__(
        self,
        close_catalog: Mapping[str, str] | None = None,
        *,
        window_lister: WindowLister = default_window_lister,
        window_activator: WindowActivator = default_window_activator,
        process_closer: ProcessCloser = default_process_closer,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create an AppControlTool.

        Args:
            close_catalog: Name -> process image name overrides, merged
                over `DEFAULT_CLOSE_CATALOG`. Only consulted by `close`.
            window_lister: Lists visible window titles. Injectable so
                tests never enumerate real windows.
            window_activator: Focuses a window by title substring.
                Injectable so tests never touch the real foreground.
            process_closer: Terminates a process by image name.
                Injectable so tests never kill a real process.
            logger: Defaults to a module logger.
        """
        merged = dict(DEFAULT_CLOSE_CATALOG)
        if close_catalog:
            merged.update(close_catalog)
        self._close_catalog = {name.lower(): image for name, image in merged.items()}
        self._window_lister = window_lister
        self._window_activator = window_activator
        self._process_closer = process_closer
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "app_control"

    @property
    def name(self) -> str:
        return "App Control"

    @property
    def description(self) -> str:
        return "Lists open application windows, switches to one, or closes a running application."

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="operation",
                description=f"One of: {', '.join(OPERATIONS)}.",
                required=True,
            ),
            ToolParameter(
                name="app_name",
                description="Which application. Required for 'switch' and 'close'; ignored for 'list'.",
                required=False,
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> AppControlResult:
        """Perform one app-control operation.

        Raises:
            ToolExecutionError: If `operation` is unrecognized, `app_name`
                is missing when required, no matching window is found
                (`switch`), or nothing was closed (`close`).
        """
        operation = require_str(arguments, "operation")
        self._logger.info("App control %s", operation)

        if operation == "list":
            return self._list()
        if operation == "switch":
            return self._switch(arguments)
        if operation == "close":
            return self._close(arguments)
        raise ToolExecutionError(
            f"Unknown app control operation {operation!r}; expected one of {OPERATIONS}."
        )

    def _list(self) -> AppControlResult:
        windows = self._window_lister()
        noun = "window" if len(windows) == 1 else "windows"
        return AppControlResult(
            operation="list", message=f"{len(windows)} open {noun}.", windows=windows
        )

    def _switch(self, arguments: dict[str, Any]) -> AppControlResult:
        app_name = self._require_app_name(arguments)
        if not self._window_activator(app_name):
            raise ToolExecutionError(f"No open window matching {app_name!r} was found.")
        return AppControlResult(operation="switch", message=f"Switched to {app_name}.")

    def _close(self, arguments: dict[str, Any]) -> AppControlResult:
        app_name = self._require_app_name(arguments)
        image = self._close_catalog.get(app_name.strip().lower(), f"{app_name}.exe")
        if not self._process_closer(image):
            raise ToolExecutionError(
                f"Could not close {app_name!r} (looked for process {image!r}); "
                "it may not be running."
            )
        return AppControlResult(operation="close", message=f"Closed {app_name}.")

    def _require_app_name(self, arguments: dict[str, Any]) -> str:
        app_name = optional_str(arguments, "app_name")
        if not app_name:
            raise ToolExecutionError("'app_name' is required for this operation.")
        return app_name
