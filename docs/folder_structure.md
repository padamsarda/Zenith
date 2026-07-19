# Folder Structure

```
main.py                        Entry point. Creates and runs the Runtime.

runtime/
    __init__.py                 Package marker only (no imports — see architecture.md).
    runtime.py                  Runtime: owns startup, shutdown, and the idle loop.
    context.py                  ApplicationContext: holds shared runtime resources.
    state.py                    RuntimeState enum.
    exceptions.py                 Exception hierarchy for the runtime's own
                                   subsystems (registry, events, commands, plugins).
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
    plugins/
        __init__.py
        state.py                   PluginState enum, TERMINAL_STATES.
        manifest.py                  PluginManifest.
        validation.py                  Plugin validation guard functions.
        plugin.py                        Plugin (abstract base class).
        context.py                        PluginContext.
        events.py                          Concrete plugin lifecycle events.
        registry.py                          PluginRegistry.

configs/
    __init__.py
    config.py                    Config dataclass and TOML loader.
    config.toml (optional)       User-provided configuration; not required.

shared/                         Generic code with no dependency on runtime/,
                                 kept reusable by anything built in this
                                 repository in the future.
    __init__.py
    exceptions.py                 ZenithError and other domain-agnostic
                                   exceptions. Runtime-subsystem-specific
                                   exceptions live in runtime/exceptions.py
                                   instead.
    utils/
        __init__.py
        time_utils.py              utc_now().
        uuid_utils.py               generate_id().
        fs_utils.py                  directory_exists(), file_exists().
        text_utils.py                is_blank_or_padded().

engineering_tools/              Standalone developer utilities that are not
                                 part of the Zenith assistant runtime. Each
                                 tool is self-contained (no dependency on
                                 runtime/, shared/, or configs/) so it can be
                                 lifted out independently in the future.
    __init__.py
    watchdog/                     Auto-resumes Claude Code after a session
                                   limit. See watchdog/README.md.

architecture/                  Architecture documentation and design records.
docs/                          Technical documentation (this folder).
plugins/                       Reserved for future plugin code on disk (loaded by
                                a future discovery/loading step). Currently empty —
                                not to be confused with runtime/plugins/, which is
                                the plugin framework itself.
tests/                         pytest test suite, one file per module under test.
```

## Purpose of each top-level directory

- **runtime/** — the assistant runtime itself: lifecycle, state, events,
  commands, plugins, configuration validation, and the exceptions
  specific to those subsystems. This is the only package `main.py`
  depends on directly.
- **configs/** — configuration loading, kept separate from `runtime/` so
  that "what the config looks like" and "how the app runs" are distinct
  concerns.
- **shared/** — generic, domain-agnostic code (exceptions, filesystem/
  time/text/UUID helpers) with no dependency on `runtime/`. Anything
  placed here should be reusable outside the assistant runtime, not just
  convenient to import from it — see the "Import direction" note in
  `docs/architecture.md`.
- **engineering_tools/** — standalone developer utilities (e.g.
  `watchdog/`) that are not part of the assistant runtime. Each tool is
  self-contained so it can be moved to its own repository later without
  entangling it with `runtime/`.
- **architecture/** — design records and architectural notes, kept
  separate from code and from the technical reference docs in `docs/`.
- **docs/** — technical reference documentation: how the system is built,
  not why decisions were made (that belongs in `architecture/`).
- **plugins/** — reserved location for future plugin code loaded from
  disk. Filesystem discovery and dynamic loading are not implemented in
  any milestone so far; see `docs/plugins.md` for the framework
  (`runtime/plugins/`) that a future loader will use.
- **tests/** — pytest suite. One test file per source module
  (`test_<module>.py`), mirroring the `runtime/`/`shared/`/`configs/`/
  `engineering_tools/` layout.
