# 0016 — Filesystem, Shell, Git, Diff, and Test Runner: the first production tool suite

- Status: Accepted
- Date: 2026-07-20

## Context

ADR 0013 shipped the `Tool`/`Skill` split and the pipeline that runs a
tool as a `Command`; the roadmap's "Zenith runtime > First real tools
and skills" item flagged what would follow once a tool could genuinely
act on the world: `AllowAllPolicy` stops being honest, and a real
`PermissionPolicy` belongs with the first such tool, not before it.
Until now every registered tool has been a test double (`ClockTool` and
its relatives) — no concrete `Tool` implementation existed under
`runtime/`. This sprint's goal was to prove the pipeline can drive real
engineering work — read/write files, run shell commands, operate a git
repository, diff two texts, run the test suite — without touching the
engine, `ToolRegistry`, `CommandExecutor`, `PermissionPolicy`, or the
provider contract.

Two problems are common to every tool that touches the filesystem or
shells out, so they needed one answer each, not five: how far can a
path argument reach, and how does a subprocess get bounded by a timeout
or stopped cooperatively.

## Decision

**Package layout.** `runtime/tools/` is the concrete-implementation
package, parallel to `runtime/providers/` (which holds `EchoProvider`,
`ScriptedProvider`, and `ClaudeProvider` alongside the abstract
contract) — `runtime/capabilities/tool.py` stays the abstract
`Tool`/`ToolParameter` definitions, and this package is where real ones
live. Five tools, one file each, plus three shared modules used by more
than one:

- **`sandbox.py`** — `resolve_within_root(root, raw_path)` is the one
  guard every path argument runs through: rejects absolute paths,
  resolves `..` against the real filesystem, and raises
  `ToolExecutionError` if the result would land outside `root`.
  `read_sandboxed_text` layers a UTF-8 decode and a size cap on top.
  `FilesystemTool`, `ShellTool` (`cwd`), `GitTool` (`add`/`diff`/`reset`
  paths), `DiffTool` (file mode), and `TestRunnerTool` (`path`) all call
  it — "well-defined interfaces rather than arbitrary unrestricted
  access" has one implementation, not five slightly different ones.
- **`process.py`** — `run_process` wraps `subprocess.Popen` with a poll
  loop (`communicate(timeout=...)`, safe to retry per the standard
  library's own documented pattern) that enforces a wall-clock timeout
  and checks `CommandContext.cancellation_token` every iteration,
  raising `CommandCancelledError` — the same reserved seam
  `docs/commands.md` describes and nothing has used yet. The child
  starts in its own process group/session
  (`CREATE_NEW_PROCESS_GROUP` / `start_new_session`) so that on timeout
  or cancellation the *whole* tree can be killed (`taskkill /F /T` /
  `killpg`) — a plain `Popen.kill()` only reaches the directly tracked
  process, and a `shell=True` command's actual program is a grandchild
  that would otherwise survive as an orphan holding the output pipes
  open, silently defeating the timeout (observed directly: an earlier
  version of this code took 30 seconds to "time out" at 0.3 seconds).
  `ShellTool`, `GitTool`, and `TestRunnerTool` all shell out through
  this one helper.
- **`arguments.py`** — `require_str`/`optional_str`/`optional_bool`/
  `optional_int`/`optional_float`/`optional_mapping`/
  `optional_sequence_str` apply one explicit type check per argument key
  against the loosely typed `dict[str, Any]` every `Tool.invoke`
  receives, raising `ToolExecutionError` on mismatch instead of each
  tool repeating `isinstance` boilerplate.

**The five tools**, each a single `operation`-style `tool_id` (mirroring
how a provider's own built-in tools — a bash tool, a text-editor tool —
are conventionally shaped) rather than one `tool_id` per verb:

- **`FilesystemTool`** — `read`/`write`/`list`/`mkdir`/`delete`/`exists`,
  sandboxed to a configured root.
- **`ShellTool`** — one command line via `shell=True`, configurable
  `cwd` (sandboxed), `env` (merged over the inherited environment), and
  `timeout_seconds`. The command itself is trusted verbatim, like a real
  terminal — sanitizing it would be both impossible to do safely and
  not this tool's job; whether it may run at all is the
  `PermissionPolicy`'s decision, made before `invoke` is ever reached.
- **`GitTool`** — `status`/`diff`/`add`/`commit`/`branch` (informational
  listing only)/`checkout`/`log` (parsed into structured `GitLogEntry`
  records)/`reset` (mixed mode only). Deliberately excludes `push`,
  `pull`, `clone`, and `--hard` — nothing this tool does can reach a
  remote or discard commits or working-tree edits. Every operation
  returns a `GitResult` carrying git's own exit code and text regardless
  of outcome; `ToolExecutionError` is reserved for this tool's own
  guards (missing repository, a path escaping the root), not for git
  reporting a normal failure (nothing to commit, merge conflict).
- **`DiffTool`** — a unified diff (`difflib`) between two inline texts
  or two sandboxed files. Independent of `GitTool`: it can compare
  anything, not just what git already tracks.
- **`TestRunnerTool`** — runs a configurable base command
  (`[sys.executable, "-m", "pytest"]` by default) with an optional test
  path/node id and extra arguments, all as argv entries, never a shell
  string. `passed`/`failed`/`errors`/`skipped` are a best-effort parse of
  the runner's own summary line — documented as exactly that, not a
  contract, since the text format belongs to the test runner, not this
  tool.

**`ToolAllowlistPolicy`** (`runtime/assistant/permissions.py`) is the
real `PermissionPolicy` the roadmap called for: an explicit set of
permitted `tool_id`s, everything else denied. It is meant to replace
`AllowAllPolicy` wherever these tools are registered; `AllowAllPolicy`
remains correct for a runtime with no tools that act.

**None of the five tools is auto-registered.** `Runtime.start` registers
`EchoProvider` as harmless scaffolding, but `ClaudeProvider` — the first
*real* provider — deliberately is not; an integrator registers it with
its own credentials where appropriate (ADR 0015). These tools follow the
`ClaudeProvider` precedent, not the `EchoProvider` one: a fresh
`python main.py` should not gain filesystem or shell access by default.
An integrator constructs each tool with the sandbox root(s) appropriate
to its deployment, registers it on `context.tools`, and pairs it with a
`ToolAllowlistPolicy` (`docs/assistant.md` documents the pattern).

## Consequences

- The engine, `ToolRegistry`, `CommandExecutor`, and provider contract
  needed zero changes — every tool is a plain `Tool` subclass invoked
  exactly like `ClockTool` was in the pipeline's own tests, which is the
  milestone's success criterion.
- `resolve_within_root` and `run_process` are now the two seams any
  *future* tool that touches paths or shells out should reuse rather
  than reimplement.
- `CommandCancelledError`/`CancellationToken` have their first real
  producer. It is still true that nothing today flips a token to
  `cancelled` mid-flight (the token is immutable once constructed, per
  `docs/commands.md`); `run_process` checking it is forward-looking, and
  directly testable today by constructing a pre-cancelled
  `CommandContext` and calling `invoke` directly.
- Structured tool results (`FilesystemResult`, `ShellResult`,
  `GitResult`, `DiffResult`, `TestRunResult`) are still stringified into
  one `TOOL` message by `ToolCallRunner` (ADR 0012's deferral stands);
  each defines `__str__` to render usefully as text, since that is
  genuinely all a provider sees today.
- A real `PermissionPolicy` now exists, but per-tool user confirmation
  does not — that remains a `before_tool` `AssistantHook`, the seam ADR
  0013 already provides, not a new mechanism this ADR invents.
- A second, materially different tool (network access, a package
  manager, a language server) is the next pressure test of
  `sandbox.py`/`process.py`'s reusability, the same way ADR 0011/0015
  frame a second provider.
