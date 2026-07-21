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
from uuid import UUID

from runtime.assistant.confirmation import ConfirmationHook
from runtime.assistant.memory_capture import MemoryCaptureHook
from runtime.assistant.permissions import ToolAllowlistPolicy
from runtime.conversation.events import ConversationArchived
from runtime.memory.sqlite.store import SQLiteMemoryStore
from runtime.providers.claude import API_KEY_ENV_VAR, ClaudeProvider
from runtime.reflection.reflector import ProviderReflector
from runtime.reflection.service import ReflectionService
from runtime.reflection.sqlite.store import SQLiteReflectionStore
from runtime.runtime import Runtime
from runtime.tools.app_control import AppControlTool
from runtime.tools.app_launcher import AppLauncherTool
from runtime.tools.diff import DiffTool
from runtime.tools.filesystem import FilesystemTool
from runtime.tools.git import GitTool
from runtime.tools.media_control import MediaControlTool
from runtime.tools.memory_tool import MemoryTool
from runtime.tools.reflection_tool import ReflectionTool
from runtime.tools.shell import ShellTool
from runtime.tools.test_runner import TestRunnerTool

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.providers.base import AssistantProvider
    from shared.events.event import Event

# Zeni's durable state lives beside the Engineering Manager's, under one
# per-user directory rather than in whatever folder it happened to be
# started from — memory that moved with the working directory would not
# be memory.
STATE_DIR = Path.home() / ".zenith"
MEMORY_DB_PATH = STATE_DIR / "memory.db"
# Reflections live in their own database, not beside memories: they are
# derived, regenerable, and deletable, and keeping them separate means
# rebuilding the derived layer can never put the raw one at risk
# (ADR 0029).
REFLECTION_DB_PATH = STATE_DIR / "reflections.db"

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
    "memory",
    "reflection",
)


def _wire_reflection(
    context: ApplicationContext, provider: AssistantProvider
) -> ReflectionService:
    """Connect the three reflection triggers, and return the service (ADR 0029).

    - **Session** subscribes to `ConversationArchived`, so a finished
      conversation is summarized without any interface knowing that
      reflection exists — `ConsoleInterface` keeps owning nothing but
      line I/O (ADR 0012).
    - **Deep** is checked once here, at startup. The runtime has no
      scheduler (ADR 0007), and for something started daily this
      approximates "every day or few days" closely enough to be honest
      about; a long-running deployment would need a real trigger.
    - **On demand** needs no wiring: it is `ReflectionTool`, registered
      alongside the rest of the suite.
    """
    service = ReflectionService(ProviderReflector(provider))

    def on_archived(event: Event) -> None:
        service.on_conversation_archived(UUID(event.payload["conversation_id"]), context)

    context.events.subscribe(ConversationArchived, on_archived)

    # Best-effort and non-blocking to startup: a deep reflection that
    # fails, or a provider that is unreachable, must never stop Zeni
    # starting.
    try:
        if service.is_deep_reflection_due(context):
            context.logger.info("Deep reflection is due; running it now.")
            service.reflect_deeply(context)
    except Exception:
        context.logger.warning("Startup deep reflection failed.", exc_info=True)

    return service


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

    provider = ClaudeProvider()
    context.assistant_providers.register(provider)

    # Durable memory replaces the in-memory default before anything can
    # write to it. Recall is automatic from here on: the assembler pulls
    # relevant memories into every brief, and MemoryCaptureHook stores
    # what is worth keeping (ADR 0027).
    context.memory = SQLiteMemoryStore(MEMORY_DB_PATH)
    context.reflections = SQLiteReflectionStore(REFLECTION_DB_PATH)

    reflection_service = _wire_reflection(context, provider)

    context.tools.register(FilesystemTool(workspace), context)
    context.tools.register(ShellTool(workspace), context)
    context.tools.register(GitTool(workspace), context)
    context.tools.register(DiffTool(workspace), context)
    context.tools.register(TestRunnerTool(workspace), context)
    context.tools.register(AppLauncherTool(), context)
    context.tools.register(AppControlTool(), context)
    context.tools.register(MediaControlTool(), context)
    context.tools.register(MemoryTool(), context)
    context.tools.register(ReflectionTool(reflection_service), context)

    context.assistant.set_permission_policy(ToolAllowlistPolicy(TOOL_IDS))
    context.assistant.add_hook(ConfirmationHook())
    context.assistant.add_hook(MemoryCaptureHook())

    context.logger.info(
        "Zeni's full capability set is registered (workspace=%s, memory=%s).",
        workspace,
        MEMORY_DB_PATH,
    )


def main() -> None:
    """Create and run the Zenith runtime."""
    workspace = Path.cwd()
    runtime = Runtime(on_start=lambda context: _wire_zeni(context, workspace))
    runtime.run()


if __name__ == "__main__":
    main()
