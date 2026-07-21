# 0025 — `main.py` as composition root, with destructive tools behind a confirmation hook

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0015 and ADR 0016 both deliberately stopped short of wiring
anything real into `python main.py`: `ClaudeProvider` and every tool in
`runtime/tools/` are library code an integrator registers explicitly,
so a fresh checkout stays inert. That was the right call while nothing
depended on it being usable. It stopped being the right call the moment
the product goal became "something to actually talk to every day" —
today, `python main.py` still only ever gets `EchoProvider`. Nothing in
the repository is a deployment; everything is a capability waiting for
one.

Wiring a real deployment raises the question ADR 0016 flagged and
deferred: `ShellTool` runs arbitrary commands and `FilesystemTool` can
overwrite or delete real files, both with the full permissions of
whoever is running Zeni. A `ToolAllowlistPolicy` decides whether a tool
may run *at all* for a deployment, but says nothing about a specific
call — approving `shell` as a class of action is not the same as
wanting every individual command it ever proposes to run unattended.

## Decision

**`main.py` becomes the composition root.** `Runtime` gains one seam,
`on_start: Callable[[ApplicationContext], None] | None`, invoked once at
the end of `start()` — after `EchoProvider` and plugins are registered,
before `state` becomes `RUNNING`. `Runtime` still knows nothing about
Claude, tools, or policies; it only calls whatever it was given, the
same shape as `PluginLoader` or `on_start=None` doing nothing at all.
`main.py`'s `_wire_zeni` is what actually decides what this machine's
Zeni can do: register `ClaudeProvider`, the full `runtime/tools/` suite
— including `AppLauncherTool`/`MediaControlTool` (ADR 0024) — a
`ToolAllowlistPolicy` naming exactly those tool IDs, and a new
`ConfirmationHook`. It is a no-op without `ANTHROPIC_API_KEY` set, so a
checkout with no credentials configured behaves exactly as before this
ADR. Registering the provider does not change
`config.assistant_provider`'s default (`"echo"`) — that stays
configuration (`configs/config.toml`), following the "swapping in a
real provider is configuration, not a code change" contract `README.md`
already documents.

**`ConfirmationHook`** (`runtime/assistant/confirmation.py`) is a
`before_tool` `AssistantHook` — the exact seam ADR 0013 and ADR 0016
both named and left unbuilt ("per-tool user confirmation... is not
built"). It gates two things only: any `shell` call (there is no
sub-operation to distinguish a safe command from a destructive one
without unreliable content-sniffing, so every call asks), and
`filesystem`'s `write`/`delete` operations (its `read`/`list`/`mkdir`/
`exists` cannot destroy anything already there). Everything else —
`git`, `diff`, `test_runner`, and both desktop-control tools — runs
unconfirmed; the allowlist is the only gate they need, since none of
them can lose data. The default `Confirmer` blocks on `input()` against
the same stdin the console reads its next line from (ADR 0007's
synchronous design); it is injected, so a future non-console interface
supplies its own and tests never block on real input.

## Consequences

- `python main.py` with `ANTHROPIC_API_KEY` set and
  `assistant_provider = "claude"` configured is now a genuinely usable
  assistant with real capability, not a pipeline nobody assembled — the
  gap the roadmap's "A real, runnable Zeni" item named.
- The blast radius this ADR actually accepts is narrower than "full
  capability by default" sounds: everything irrecoverable requires an
  explicit yes on the console, per call. What's unattended is exactly
  the set of actions that cannot lose data.
- `Runtime.on_start` is a generic extension point, not specific to this
  deployment — any future integration (a test harness, a different
  personal deployment, a packaged distribution) can compose its own
  capability set the same way, without `Runtime` changing again.
- The console-blocking default `Confirmer` is a real limitation for any
  future non-console interface (voice, GUI, network): none of them has
  a stdin to block on. That is an explicit deferral, not an oversight —
  `ConsoleInterface` remains the only interface that exists, and the
  `Confirmer` seam is exactly what a future one overrides.
- `AssistantEngine` gained a `hooks` property (mirroring the existing
  `permission_policy` one) purely so tests and future integrators can
  inspect what is attached without reaching into a private list.
