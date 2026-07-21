"""Entry point for the Zenith runtime — and Zeni's composition root.

`Runtime` is generic infrastructure; it has no idea what a "real"
deployment looks like, on purpose (ADR 0015, ADR 0016). This module is
the specific deployment: it decides what Zeni can actually do when
someone runs `python main.py` on this machine. `_wire_zeni` is a no-op
without `ANTHROPIC_API_KEY` set, so that absence keeps today's behavior
(EchoProvider only, no tools) exactly as it was before this existed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from runtime.assistant.confirmation import ConfirmationHook
from runtime.assistant.permissions import ToolAllowlistPolicy
from runtime.providers.claude import API_KEY_ENV_VAR, ClaudeProvider
from runtime.runtime import Runtime
from runtime.tools.app_control import AppControlTool
from runtime.tools.app_launcher import AppLauncherTool
from runtime.tools.diff import DiffTool
from runtime.tools.filesystem import FilesystemTool
from runtime.tools.git import GitTool
from runtime.tools.media_control import MediaControlTool
from runtime.tools.shell import ShellTool
from runtime.tools.test_runner import TestRunnerTool

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

# Every tool_id registered by _wire_zeni, in one place so the allowlist
# can never drift from what was actually registered.
TOOL_IDS = (
    "filesystem",
    "shell",
    "git",
    "diff",
    "test_runner",
    "app_launcher",
    "app_control",
    "media_control",
)


def _wire_zeni(context: ApplicationContext, workspace: Path) -> None:
    """Register Zeni's real capabilities, if credentials are available.

    Set `assistant_provider = "claude"` in `configs/config.toml` to
    actually start using what this registers — registering the provider
    only makes it available, the same "configuration, not a code change"
    contract every other provider swap already follows (`README.md`).

    `ShellTool`'s commands, `FilesystemTool`'s `write`/`delete`, and
    `AppControlTool`'s `close` go through `ConfirmationHook` (ADR 0025,
    ADR 0026), which asks on the console before each one runs; everything
    else in the suite, including opening apps, listing/switching windows,
    and media control (ADR 0024), runs unconfirmed — the
    `ToolAllowlistPolicy` below is what stands between an unregistered
    tool and the model, not a per-call checkpoint, for the tools that
    cannot destroy anything irrecoverably.
    """
    if not os.environ.get(API_KEY_ENV_VAR):
        context.logger.info(
            "%s not set; Zeni's real provider and tools are not registered.",
            API_KEY_ENV_VAR,
        )
        return

    context.assistant_providers.register(ClaudeProvider())

    context.tools.register(FilesystemTool(workspace), context)
    context.tools.register(ShellTool(workspace), context)
    context.tools.register(GitTool(workspace), context)
    context.tools.register(DiffTool(workspace), context)
    context.tools.register(TestRunnerTool(workspace), context)
    context.tools.register(AppLauncherTool(), context)
    context.tools.register(AppControlTool(), context)
    context.tools.register(MediaControlTool(), context)

    context.assistant.set_permission_policy(ToolAllowlistPolicy(TOOL_IDS))
    context.assistant.add_hook(ConfirmationHook())

    context.logger.info(
        "Zeni's full capability set is registered (workspace=%s).", workspace
    )


def main() -> None:
    """Create and run the Zenith runtime."""
    workspace = Path.cwd()
    runtime = Runtime(on_start=lambda context: _wire_zeni(context, workspace))
    runtime.run()


if __name__ == "__main__":
    main()
