"""Entry point for the Engineering Manager CLI.

Parses arguments (`cli_parser`), opens the store, dispatches the command
(`cli_commands`), and turns any `EngineeringManagerError` into a clean
message and a nonzero exit code — the one place operational failure
becomes a process result.

Usage: `python -m engineering_manager [--db PATH] <command> ...`
"""

from __future__ import annotations

import sys

from engineering_manager.cli_commands import dispatch
from engineering_manager.cli_parser import (
    DEFAULT_DB_PATH,
    DEFAULT_TICK_INTERVAL_SECONDS,
    build_parser,
)
from engineering_manager.exceptions import EngineeringManagerError
from engineering_manager.manager import EngineeringManager
from engineering_manager.store.store import Store

__all__ = ["DEFAULT_DB_PATH", "DEFAULT_TICK_INTERVAL_SECONDS", "build_parser", "main"]


def _use_utf8_output() -> None:
    """Make stdout/stderr carry the text the commands actually produce.

    Plans, task titles, and engineering reports are prose written by
    humans and models, so they routinely contain em dashes and other
    non-ASCII characters. On a Windows console the default encoding is a
    legacy code page, which renders those as replacement characters —
    `project report` printed mojibake while the same report written with
    `--out` (explicitly UTF-8) was perfect.

    Reconfiguring is best-effort: a stream that has been replaced by a
    test harness or a pipe wrapper may not support it, and garbled output
    is never worth failing a command over.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; return a process exit code."""
    _use_utf8_output()
    args = build_parser().parse_args(argv)
    manager = EngineeringManager(Store(args.db))
    try:
        dispatch(manager, args)
    except EngineeringManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        manager.close()
    return 0
