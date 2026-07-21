# 0024 — Desktop control: the first tools that act on the OS, not a sandboxed root

- Status: Accepted
- Date: 2026-07-21

## Context

The product direction for `runtime/` was sharpened: Zenith is the
platform, but what it is building is **Zeni**, a personal assistant
meant to replace the keyboard and mouse for everyday tasks — "open
Spotify and play something," "pause the music," "increase the volume,"
"open KiCad." None of ADR 0016's tool suite touches this. Filesystem,
Shell, Git, Diff, and Test Runner are all scoped to a project: every
path argument is resolved through `resolve_within_root` against a
configured sandbox, because their entire job is acting *inside* a
repository. Opening an application or pressing a volume key has no
project to be sandboxed to — the action's target is the desktop itself.

This is a real gap in the tool contract's coverage, not an oversight:
until now, nothing Zenith could do reached outside a directory tree it
was explicitly configured with. Something has to define what "the
`PermissionPolicy` is the boundary, not a sandbox root" looks like for a
tool that has no root to sandbox.

## Decision

Add two tools to `runtime/tools/`, same package, same `Tool` contract,
same non-auto-registered precedent as ADR 0016 — nothing here changes
the engine, `ToolRegistry`, `CommandExecutor`, or `PermissionPolicy`.

- **`AppLauncherTool`** (`app_launcher`) — opens an application, file,
  URL, or anything else the OS can resolve by name. A small, overridable
  `catalog` maps a handful of everyday names (`"vs code"`, `"spotify"`,
  `"github"`, ...) to the command to launch; a name absent from the
  catalog passes through unchanged, which still resolves for anything
  registered on PATH or under Windows' "App Paths" key — the exact
  lookup a typed name gets in the Run dialog. Launching is
  fire-and-forget: unlike `ShellTool`, it never waits for the process to
  exit, since blocking the conversation until the user closes Spotify
  would defeat the point.
- **`MediaControlTool`** (`media_control`) — sends the same virtual-key
  events a hardware media/volume key sends (`play_pause`,
  `next_track`/`previous_track`, `mute`, `volume_up`/`volume_down`,
  optionally repeated `steps` times). This is deliberately relative, not
  an absolute level: a real level requires the Windows Core Audio COM
  API, which has no stdlib binding, and the project's dependency policy
  (`docs/conventions.md`) does not admit one for this.

**Neither is sandboxed to a root** — there is nothing to sandbox to.
The boundary is the same one every tool already has: the
`PermissionPolicy` evaluated before `invoke` is ever reached. A
deployment that wants these tools available pairs them with a
`ToolAllowlistPolicy` exactly as ADR 0016 already recommends; nothing
about that seam changed.

**The OS-specific action is injected, not hardcoded**, mirroring
`ClaudeCodeProvider`'s `Launcher` (ADR 0014) and `run_process`'s
`cancellation_token` seam (ADR 0016): `AppLauncherTool` takes a
`Launcher` (`Callable[[str], None]`, default `os.startfile`/`Popen`),
`MediaControlTool` takes a `KeySender` (`Callable[[int], None]`, default
`ctypes.windll.user32.keybd_event`). This is what keeps both tools fully
unit-testable on the project's `ubuntu-latest` CI matrix despite being
Windows tools in practice — the injected fake never touches a real
process or the real keyboard input queue, and `default_key_sender`
itself is directly exercised on Linux by asserting it fails loudly
rather than silently doing nothing off Windows, the same principle ADR
0022 established for a session that cannot act.

## Consequences

- This is the first tool suite whose action is not confined to a
  directory a deployment chose — `app_launcher` can open anything the OS
  will resolve by name, and `media_control` affects whatever application
  currently owns media focus, system-wide. Deployments should treat
  `ToolAllowlistPolicy` as load-bearing here even more than for ADR
  0016's suite, since there is no second boundary underneath it.
- `AppLauncherTool`'s default catalog is small and opinionated — the
  handful of names the product vision itself names as daily examples.
  Growing it for a specific machine's installed applications is
  configuration at registration time (`catalog=`), not a code change.
- Closing or switching between running applications, listing what is
  running, Bluetooth, and display management are named in the product
  vision but not built here — each is a materially different mechanism
  (window enumeration, device management APIs) and stays open rather
  than half-built alongside these two.
- No new dependency: `ctypes` and `os.startfile`/`subprocess.Popen` are
  standard library. The absolute-volume deferral above is the direct
  consequence of holding that line rather than reaching for `pycaw` or
  `comtypes`.
