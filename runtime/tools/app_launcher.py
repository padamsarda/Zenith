"""AppLauncherTool: opens a desktop application by name."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import require_str

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.app_launcher"

# Common names resolved to a command `default_launcher` can act on
# directly. A name not listed here is passed through verbatim, which
# still resolves for anything registered under the Windows "App Paths"
# key or present on PATH — the same lookup a typed name gets in the Run
# dialog or Start menu. This catalog exists only for the names that need
# a different token than the one a person would say: a URL for a service
# with no local executable, or a alias shorter than its real command.
DEFAULT_CATALOG: Mapping[str, str] = {
    "vs code": "code",
    "vscode": "code",
    "code": "code",
    "spotify": "spotify",
    "chrome": "chrome",
    "browser": "chrome",
    "notion": "notion",
    "kicad": "kicad",
    "explorer": "explorer",
    "files": "explorer",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "terminal": "cmd",
    "github": "https://github.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
}

Launcher = Callable[[str], None]


def default_launcher(command: str) -> None:
    """Launch `command` without waiting for it to exit.

    On Windows, `os.startfile` is the same resolution a typed name gets
    in the Run dialog: the "App Paths" registry key, PATH, or — for a
    `http(s)://` command — the default browser. Elsewhere, `Popen` is a
    best-effort fallback for development off Windows.

    Raises:
        OSError: If the command could not be resolved or started.
    """
    if sys.platform == "win32":
        os.startfile(command)  # type: ignore[attr-defined]
    else:
        subprocess.Popen([command])


@dataclass(frozen=True)
class AppLaunchResult:
    """The structured outcome of one launch attempt."""

    app_name: str
    command: str
    message: str

    def __str__(self) -> str:
        return self.message


class AppLauncherTool(Tool):
    """Opens a desktop application, given its everyday name.

    Resolution is a small, overridable catalog (`catalog`, defaulting to
    `DEFAULT_CATALOG`) mapping a lowercased name to the command
    `launcher` should act on; a name absent from the catalog is passed
    through unchanged, which still resolves for anything the operating
    system itself can find by name. Launching is fire-and-forget —
    unlike `ShellTool`, this tool never waits for the application to
    exit, so opening Spotify does not block the conversation until the
    user closes it.
    """

    def __init__(
        self,
        catalog: Mapping[str, str] | None = None,
        *,
        launcher: Launcher = default_launcher,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create an AppLauncherTool.

        Args:
            catalog: Name -> command overrides, merged over
                `DEFAULT_CATALOG` (an entry here wins on a shared key).
                `None` uses the default catalog unchanged.
            launcher: How a resolved command is actually launched.
                Injectable so tests never spawn a real process.
            logger: Defaults to a module logger.
        """
        merged = dict(DEFAULT_CATALOG)
        if catalog:
            merged.update(catalog)
        self._catalog = {name.lower(): command for name, command in merged.items()}
        self._launcher = launcher
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "app_launcher"

    @property
    def name(self) -> str:
        return "App Launcher"

    @property
    def description(self) -> str:
        return "Opens a desktop application, website, or file by its everyday name."

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="app_name",
                description="What to open, e.g. 'Spotify', 'VS Code', 'github'.",
                required=True,
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> AppLaunchResult:
        """Launch the requested application.

        Raises:
            ToolExecutionError: If the resolved command could not be
                launched (not found, not executable, OS refused it).
        """
        app_name = require_str(arguments, "app_name")
        command = self._catalog.get(app_name.strip().lower(), app_name)

        self._logger.info("Opening %r (command=%r)", app_name, command)
        try:
            self._launcher(command)
        except OSError as exc:
            raise ToolExecutionError(f"Could not open {app_name!r}: {exc}") from exc

        return AppLaunchResult(
            app_name=app_name, command=command, message=f"Opened {app_name}."
        )
