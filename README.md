# Zenith

Zenith is a long-term software project providing a runtime platform for building and
operating an assistant called **Zeni**. Zeni runs on top of the Zenith runtime.

This repository is under incremental, long-term development. The current milestone
(Milestone 2: core infrastructure and event system) adds an `ApplicationContext`,
a `ServiceRegistry`, and a synchronous in-process `EventBus` that the runtime uses
to announce its own lifecycle. No assistant behavior, plugins, or integrations have
been implemented yet.

## Project structure

See [`docs/folder_structure.md`](docs/folder_structure.md) for the full, up-to-date
directory listing. Summary:

- **runtime/** — the assistant runtime: lifecycle (`runtime.py`), shared
  resources (`context.py`), state (`state.py`), runtime-subsystem errors
  (`exceptions.py`), logging (`logging_setup.py`), the service registry
  (`registry.py`), validation (`validation.py`), the event system (`events/`),
  the command framework (`commands/`), and the plugin framework (`plugins/`).
  This is the only package `main.py` depends on directly.
- **configs/** — centralized configuration loading. Provides an immutable `Config`
  object built from defaults, optionally overridden by `configs/config.toml`.
- **shared/** — generic, domain-agnostic code with no dependency on `runtime/`:
  a base exception hierarchy (`exceptions.py`) and small helpers (`utils/`) for
  time, UUIDs, the filesystem, and text. Kept reusable outside the assistant
  runtime by design.
- **engineering_tools/** — standalone developer utilities that are not part of
  the assistant runtime (e.g. `watchdog/`, which auto-resumes Claude Code after
  a session limit). Each tool is self-contained.
- **architecture/** — design records and architectural notes, kept separate from code.
- **docs/** — technical documentation: architecture, the event system, the service
  registry, folder responsibilities, and development conventions.
- **plugins/** — reserved location for future plugin code. Not yet implemented.
- **tests/** — pytest test suite, one file per source module.

## Further reading

- [`docs/architecture.md`](docs/architecture.md) — runtime lifecycle and module map.
- [`docs/events.md`](docs/events.md) — the event system.
- [`docs/service_registry.md`](docs/service_registry.md) — the service registry.
- [`docs/conventions.md`](docs/conventions.md) — development conventions.

## Requirements

- Python 3.12+

## Running

```bash
python main.py
```

This prints a startup banner, verifies the project's required folders exist, loads
configuration (or falls back to defaults if `configs/config.toml` is absent), and
then idles until interrupted with Ctrl+C, at which point it shuts down gracefully.

## Development

Install test dependencies and run the test suite:

```bash
pip install -e ".[dev]"
pytest
```

## Development philosophy

Zenith is built incrementally, one deliberate milestone at a time. Each milestone
implements only what has been explicitly scoped for it — no speculative features,
no architecture invented ahead of need. Code favors readability over cleverness,
keeps each file focused on a single responsibility, and avoids external dependencies
unless they are genuinely required.
