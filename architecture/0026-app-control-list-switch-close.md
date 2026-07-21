# 0026 — App control: listing, switching, and closing running applications

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0024 shipped `AppLauncherTool` and `MediaControlTool`, and named
what it deliberately left out: "closing or switching between running
applications, listing what is running... stays open rather than
half-built alongside these two." That gap is next — it's the other
half of the product vision's own "Desktop Control" list, and unlike
opening an app, it needs a different mechanism entirely: `open` starts
a new process by name; `list`/`switch`/`close` all operate on
applications that already exist, which means enumerating and acting on
live windows and processes rather than resolving a name to a launch
command.

## Decision

Add `AppControlTool` (`app_control`, `runtime/tools/app_control.py`) —
`AppLauncherTool`'s complement, bundled the way ADR 0016 bundles verbs
that share one mechanism (window enumeration for `list`/`switch`,
process termination for `close`), rather than three separate tools.

- **`list`** — every visible top-level window's title, via `EnumWindows`
  (`ctypes`, no new dependency).
- **`switch`** — brings the first window whose title contains the given
  name (case-insensitive) to the foreground via `SetForegroundWindow`.
  Windows itself may still refuse to hand over focus depending on what
  currently has it — this is an OS policy the tool does not attempt to
  work around (e.g. with `AttachThreadInput` tricks), so `switch`
  reports whether a matching window was *found*, not that it definitely
  ended up frontmost.
- **`close`** — force-terminates every process matching a name, resolved
  through a small overridable catalog to an exact process image name
  (`"spotify"` -> `"Spotify.exe"`), falling back to `"<name>.exe"` for
  anything not listed. Uses `taskkill /IM ... /F`, the same
  "shell out to the OS's own command" approach `GitTool`/`TestRunnerTool`
  already use rather than reimplementing process management.

**`close` joins `ConfirmationHook`'s gated set** (ADR 0025). Everything
else in the desktop-control suite is safe to run unattended because
none of it can lose data — `close` breaks that pattern: force-killing a
process can discard unsaved work exactly the way `filesystem.delete`
discards a file. `list` and `switch` stay ungated; both are read-only or
trivially reversible. This is additive to ADR 0025's mechanism, not a
reversal of its decision — the hook's gated-call set was never presented
as closed, and this is its first extension.

All three OS-facing actions (`window_lister`, `window_activator`,
`process_closer`) are injected, following ADR 0024's precedent exactly,
so the tool is fully unit-tested on the Linux CI matrix and the real
Windows-backed defaults are exercised only in practice — including
`ToolExecutionError` on non-Windows, directly assertable on Linux the
same way `default_key_sender` already is.

## Consequences

- The product vision's Desktop Control list is now fully covered except
  Bluetooth and display management, which remain open — genuinely
  different mechanisms again, not a natural extension of this tool.
- `close`'s catalog is separate from `AppLauncherTool`'s: opening
  "spotify" needs a launchable command or URL, closing it needs an exact
  process image name. The two are not interchangeable, so they are not
  shared, even though both are keyed by the same kind of everyday name.
- `main.py`'s `_wire_zeni` (ADR 0025) registers `AppControlTool`
  alongside the rest of the suite and adds `"app_control"` to the
  allowlist; no other change to the composition root was needed.
