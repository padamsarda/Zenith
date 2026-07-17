# Folder Structure

```
main.py                        Entry point. Creates and runs the Runtime.

runtime/
    __init__.py                 Package marker only (no imports — see architecture.md).
    runtime.py                  Runtime: owns startup, shutdown, and the idle loop.
    context.py                  ApplicationContext: holds shared runtime resources.
    state.py                    RuntimeState enum.
    exceptions.py                Zenith exception hierarchy.
    logging_setup.py             Console logging configuration.
    registry.py                  ServiceRegistry.
    validation.py                 Validation guard functions.
    events/
        __init__.py
        event.py                  Event base class.
        lifecycle_events.py        Concrete runtime lifecycle events.
        bus.py                     EventBus.
        event_logger.py            EventLogger.
    commands/
        __init__.py
        status.py                  CommandStatus enum, TERMINAL_STATUSES.
        validation.py               Command validation guard functions.
        command.py                  Command.
        result.py                    CommandResult.
        context.py                    CommandContext, CancellationToken.
        events.py                      Concrete command lifecycle events.
        executor.py                     CommandExecutor.
    utils/
        __init__.py
        time_utils.py              utc_now().
        uuid_utils.py               generate_id().
        fs_utils.py                  directory_exists(), file_exists().
        text_utils.py                is_blank_or_padded().

configs/
    __init__.py
    config.py                    Config dataclass and TOML loader.
    config.toml (optional)       User-provided configuration; not required.

architecture/                  Architecture documentation and design records.
docs/                          Technical documentation (this folder).
plugins/                       Reserved for future plugin code. Currently empty.
tests/                         pytest test suite, one file per module under test.
```

## Purpose of each top-level directory

- **runtime/** — the core of the application: lifecycle, state, events,
  configuration validation, and small internal utilities. This is the
  only package `main.py` depends on directly.
- **configs/** — configuration loading, kept separate from `runtime/` so
  that "what the config looks like" and "how the app runs" are distinct
  concerns.
- **architecture/** — design records and architectural notes, kept
  separate from code and from the technical reference docs in `docs/`.
- **docs/** — technical reference documentation: how the system is built,
  not why decisions were made (that belongs in `architecture/`).
- **plugins/** — reserved location for future plugin code. Not
  implemented in this milestone.
- **tests/** — pytest suite. One test file per source module
  (`test_<module>.py`), mirroring the `runtime/`/`configs/` layout.
