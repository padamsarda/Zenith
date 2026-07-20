# 0014 — Claude Code CLI as the Engineering Manager's first real Provider

- Status: Accepted
- Date: 2026-07-20

## Context

ADR 0005 defined `Provider` against no real integration, deliberately:
`InMemoryProvider` proved the contract; a real adapter was roadmap item
one, expected to generalize `engineering_tools/watchdog`, which already
solves the hard part by hand — running Claude Code as a subprocess,
detecting its session-limit message, parsing the reset time, and
resuming with `claude --continue`. The question this ADR answers is how
that manual loop becomes four `Provider` methods without rewriting logic
the watchdog's own test suite already proves correct.

## Decision

`ClaudeCodeProvider` (`engineering_manager/providers/claude_code.py`)
runs `claude --print <instructions> --output-format json` as one
non-interactive subprocess per session, in the task's project directory:

- **`start_session`** launches the subprocess (via an injectable
  `Launcher`, matching `Provider.check_session`'s poll-based contract —
  nothing blocks waiting for the task to finish) and tracks it, keyed by
  a freshly generated `external_ref`, alongside an `OutputDrain`: a
  background thread that continuously reads the process's combined
  stdout/stderr so a chatty, long-running task cannot deadlock on a full
  OS pipe buffer between polls.
- **`check_session`** polls the process. Still running -> `RUNNING`. A
  zero exit is parsed as the CLI's own `--output-format json` result
  (`is_error` distinguishes an application-level failure from success,
  both still a clean process exit). A nonzero exit is scanned for the
  literal line the watchdog already detects — extracted from
  `engineering_tools/watchdog/watchdog.py` as `SESSION_LIMIT_MARKER`,
  used alongside its `parse_reset_time`, both reused rather than
  reimplemented — reporting `LIMIT_REACHED` with the parsed `resume_at`,
  or `FAILED` otherwise.
- **`resume_session`** starts a fresh `claude --continue --print
  <resume prompt>` subprocess in the same directory and issues a new
  `external_ref`, exactly the recovery the watchdog performs by hand,
  now automatic through the `ExecutionEngine`'s resume phase (ADR 0008).
- **`stop_session`** terminates the subprocess, escalating to a kill if
  it does not exit promptly.

Two small, additive consequences fall out of building this for real:

- **A new cross-package import.** `engineering_manager` now imports from
  `engineering_tools.watchdog` — an edge ADR 0002's hard boundary does
  not mention, because `engineering_tools/` sits outside the two
  applications it governs. This is deliberately one-directional and
  costs `engineering_tools` nothing: its own dependencies are unchanged
  (still zero, still liftable independently), and the parsing logic
  gains a second, real consumer of the same tested implementation
  instead of a second copy of the same regex.
- **`ProviderSessionStatus` gains `usage: dict[str, Any] | None = None`.**
  `--output-format json` reports token counts and cost per session; ADR
  0005 anticipated the contract growing additively as a real integration
  demanded it, and usage accounting is exactly that demand. The field
  defaults to `None` and no existing provider or test needed to change.

Credentials are resolved from the account ID, never stored by the
Engineering Manager (ADR 0005): an account `"personal"` looks for
`ZENITH_CLAUDE_PERSONAL_API_KEY`; if unset, the subprocess inherits the
environment unchanged and relies on however `claude` is already
authenticated on the machine.

## Consequences

- Session tracking (the process handle, its drain thread) is in-memory
  only. An Engineering Manager restart loses it for any session still
  running; that session's next `check_session` raises
  `ProviderSessionError` for the unknown handle, which the execution
  engine already treats as lost work and recovers via the retry policy
  (ADR 0008) — the same category of limitation `ConversationStore`
  accepts for the Zenith runtime, not a new one.
- There is no session-length timeout: Claude Code sessions may
  legitimately run for hours, and the engine's poll interval — not this
  provider — governs how promptly completion is noticed.
- `engineering_manager/cli.py` gains a `run` subcommand that registers
  `ClaudeCodeProvider` and calls `manager.run()`, closing out roadmap
  item one ("with one real adapter, expose `run` in the CLI").
- A second real adapter (e.g. an HTTP-API provider) remains the next
  pressure test of the contract's provider-agnosticism, unaffected by
  anything decided here.
