# Zenith

Zenith is a long-term software project providing a runtime platform for building and
operating an assistant called **Zeni**. Zeni runs on top of the Zenith runtime.

This repository is under incremental, long-term development. The current milestone
(Milestone 1: Runtime Foundation) establishes the core lifecycle, configuration, and
logging infrastructure. No assistant behavior, plugins, or integrations have been
implemented yet.

## Project structure

```
main.py                    Entry point. Creates and runs the Runtime.
runtime/
    __init__.py             Runtime package marker.
    runtime.py               Runtime class: owns startup, shutdown, and the idle loop.
    state.py                 RuntimeState enum describing lifecycle states.
    exceptions.py             Zenith exception hierarchy (ZenithError and subclasses).
    logging_setup.py          Console logging configuration.
configs/
    __init__.py              Configuration package marker.
    config.py                 Immutable Config dataclass and TOML loader.
    config.toml (optional)    User-provided configuration; not required.
architecture/               Architecture documentation and design records.
docs/                       General project documentation.
plugins/                    Reserved for future plugin code. Currently empty.
tests/                      Automated tests (pytest).
```

### Purpose of each directory

- **runtime/** — the core of the application. Owns the lifecycle (startup, running,
  shutdown), logging, and the runtime state machine. This is the only package that
  `main.py` depends on directly.
- **configs/** — centralized configuration loading. Provides an immutable `Config`
  object built from defaults, optionally overridden by `configs/config.toml`.
- **architecture/** — design records and architectural notes, kept separate from code.
- **docs/** — general-purpose documentation that isn't architecture-specific.
- **plugins/** — reserved location for future plugin code. Not yet implemented.
- **tests/** — pytest test suite covering configuration, runtime state transitions,
  runtime lifecycle, and the exception hierarchy.

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
