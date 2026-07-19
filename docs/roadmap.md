# Roadmap

Where this repository is headed, in dependency order. Each item builds
on what exists; none requires reworking current foundations. This file
is direction, not commitment — reorder freely, but record significant
design choices as ADRs (`architecture/`) when implementing.

## Engineering Manager

### 1. First real provider adapter (highest value)

A `Provider` implementation that drives Claude Code as a subprocess,
generalizing `engineering_tools/watchdog`: start a session in a
project's working directory (`start_session`), detect completion and
session limits (`check_session` reporting `LIMIT_REACHED` with
`resume_at`), resume with `--continue` (`resume_session`), terminate
(`stop_session`). The watchdog's parsing logic (limit detection, reset
times) is proven and should be extracted, tested, and reused rather
than rewritten. A second adapter (e.g. an HTTP-API provider) will then
pressure-test the contract's provider-agnosticism; extend
`Provider`/`SessionSpec` additively if it falls short (ADR 0005).

### 2. The scheduler loop

A long-running `run` command: poll open sessions via `check_session`,
call `complete_session`/`fail_session`/`interrupt_session` as states
change, `resume_session` when a `LIMIT_REACHED` session's `resume_at`
passes, and `dispatch()` whenever accounts free up. Every building
block exists and is tested; the loop is plain sequential polling
(ADR 0007). Notification to the human (tasks reaching `NEEDS_REVIEW`)
belongs here too, starting with the CLI `status`/`log` views.

### 3. Session context handoff

When a session ends, what it learned survives only in `summary`. Add
structured handoff: a per-task context document the next session (or a
rework attempt) receives via `SessionSpec`. Design questions —
authored by the provider? distilled by a cheap model? size limits? —
deserve an ADR.

### 4. Richer assignment policies

`FirstAvailablePolicy` ignores cost, capability, and history. Add
policies using per-provider concurrency limits, model/task matching
(`SessionSpec.model` is already plumbed), and past outcomes (the event
log already records them). The `AssignmentPolicy` seam absorbs all of
this without dispatcher changes.

### 5. Store hardening as concurrency arrives

When the scheduler loop and CLI can write concurrently: a unit-of-work
(one transaction spanning dispatch's task update + session insert),
`busy_timeout`, and possibly a join table for dependencies if SQL-side
queries become useful (ADR 0004 anticipates all three).

### 6. Zenith as a managed project

The closing of the loop: a `zenith` project whose tasks are Zenith
milestones, dispatched to providers by the Engineering Manager. No new
mechanism is expected — this is dogfooding, and the friction it finds
feeds items 1–5.

## Zenith runtime

Continues its milestone-driven path independently (ADR 0002), with the
existing command and plugin frameworks as extension points:

- **Plugin loading** — discovery/import from `plugins/` into the
  existing `PluginRegistry`; the framework and events already exist.
- **First real capabilities** — assistant behaviors executed as
  `Command`s through the `CommandExecutor` so they are validated,
  timed, and observable from day one.
- **Richer configuration** — `configs.Config` grows fields as features
  need them; validation lives in `runtime/validation.py`.

## Repository-wide

- **Lint/format tooling** — the codebase is hand-consistent; if drift
  appears as more contributors (human or AI) join, adopt ruff as a
  dev-only dependency via an ADR amending the dependency convention.
- **CI** — `pip install -e ".[dev]" && pytest` is the whole gate; wire
  it to whichever host the repository lands on.
