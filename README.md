# Zenith

This repository hosts two applications built on one shared foundation:

- **Zenith** (`runtime/`) — a runtime platform for building and
  operating an assistant called **Zeni**. It provides lifecycle
  management, an event system, a command execution framework, and a
  plugin framework. Assistant capabilities land on top of these.
- **Engineering Manager** (`engineering_manager/`) — a local-first
  platform for coordinating AI-performed engineering work across
  projects, providers (Claude, Gemini, Codex, …), and accounts. The
  long-term intent is for Zenith itself to become one of its managed
  projects.

The two applications never import each other; `shared/` (exceptions,
event system, small utilities) is the only common layer. See
[ADR 0002](architecture/0002-two-applications-over-shared-infrastructure.md).

## Project structure

See [`docs/folder_structure.md`](docs/folder_structure.md) for the full
listing. Summary:

- **runtime/** — the Zenith assistant runtime: lifecycle, state,
  service registry, command framework, plugin framework, and the
  runtime's own event types.
- **engineering_manager/** — the Engineering Manager: domain model
  (projects, tasks, sessions, accounts), provider abstraction, SQLite
  persistence with an event log, orchestration, and a CLI.
- **shared/** — infrastructure both applications use: base exceptions,
  the event system (`shared/events/`), and small utilities.
- **configs/** — configuration loading for the Zenith runtime.
- **engineering_tools/** — standalone developer utilities (e.g.
  `watchdog/`, which auto-resumes Claude Code after a session limit).
- **architecture/** — Architecture Decision Records. Start with
  [`architecture/README.md`](architecture/README.md).
- **docs/** — technical reference documentation.
- **plugins/** — reserved location for future Zenith plugin code.
- **tests/** — pytest suite, one file per source module.

## Requirements

- Python 3.12+ (standard library only; `pytest` is the sole
  development dependency)

## Running Zenith

```bash
python main.py
```

Prints a startup banner, verifies the project layout, loads
configuration (defaults if `configs/config.toml` is absent), and idles
until Ctrl+C shuts it down gracefully.

## Running the Engineering Manager

```bash
python -m engineering_manager project add zenith "Zenith" --path .
python -m engineering_manager task add zenith "Implement plugin loading" --priority 5
python -m engineering_manager task approve <task-id>
python -m engineering_manager status
```

State persists in `~/.zenith/engineering_manager.db` (override with
`--db`). See [`docs/engineering_manager.md`](docs/engineering_manager.md)
for the architecture and programmatic API, and
[`docs/roadmap.md`](docs/roadmap.md) for what comes next.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Read [`docs/conventions.md`](docs/conventions.md) before writing code,
and [`CLAUDE.md`](CLAUDE.md) if you are an AI contributor. Significant
architectural decisions are recorded in [`architecture/`](architecture/).

## Further reading

- [`docs/architecture.md`](docs/architecture.md) — Zenith runtime internals.
- [`docs/engineering_manager.md`](docs/engineering_manager.md) — Engineering Manager architecture.
- [`docs/events.md`](docs/events.md) — the shared event system.
- [`docs/commands.md`](docs/commands.md) — the command execution framework.
- [`docs/plugins.md`](docs/plugins.md) — the plugin framework.
- [`docs/service_registry.md`](docs/service_registry.md) — the service registry.
- [`docs/roadmap.md`](docs/roadmap.md) — where this is all headed.

## Development philosophy

Both applications are built incrementally, one deliberate milestone at
a time — no speculative features, no architecture invented ahead of
need. Code favors readability over cleverness, keeps each file focused
on a single responsibility, and avoids external dependencies unless
they are genuinely required. Decisions that shape the architecture are
recorded as ADRs so their reasoning outlives their authors.
