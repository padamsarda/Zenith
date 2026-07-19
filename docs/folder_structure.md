# Folder Structure

```
main.py                        Entry point for the Zenith runtime.

runtime/                       The Zenith assistant runtime.
    __init__.py                 Package marker only (no imports — see architecture.md).
    runtime.py                  Runtime: owns startup, shutdown, and the idle loop.
    context.py                  ApplicationContext: holds shared runtime resources.
    state.py                    RuntimeState enum.
    exceptions.py               Exceptions for the runtime's own subsystems
                                 (registry, commands, plugins).
    logging_setup.py            Console logging configuration.
    registry.py                 ServiceRegistry.
    validation.py               Validation guard functions.
    events/
        lifecycle_events.py      Concrete runtime lifecycle events. (The event
                                  system itself lives in shared/events/.)
    commands/
        status.py                CommandStatus enum, TERMINAL_STATUSES.
        validation.py            Command validation guard functions.
        command.py               Command.
        result.py                CommandResult.
        context.py               CommandContext, CancellationToken.
        events.py                Concrete command lifecycle events.
        executor.py              CommandExecutor.
    plugins/
        state.py                 PluginState enum, TERMINAL_STATES.
        manifest.py              PluginManifest.
        validation.py            Plugin validation guard functions.
        plugin.py                Plugin (abstract base class).
        context.py               PluginContext.
        events.py                Concrete plugin lifecycle events.
        registry.py              PluginRegistry.

engineering_manager/           The Engineering Manager application.
    __init__.py                 Package docstring only.
    __main__.py                 `python -m engineering_manager` entry point.
    cli.py                      Command-line interface over the facade.
    manager.py                  EngineeringManager facade.
    events.py                   Concrete Engineering Manager events.
    exceptions.py               EM exception hierarchy (rooted at ZenithError).
    domain/
        states.py                ProjectStatus, TaskStatus, SessionStatus + terminals.
        validation.py            Structural and transition guard functions.
        project.py               Project.
        task.py                  Task.
        session.py               Session.
        account.py               ProviderAccount.
    providers/
        base.py                  Provider ABC, SessionSpec, SessionHandle,
                                  ProviderSessionState, ProviderSessionStatus.
        registry.py              ProviderRegistry.
        in_memory.py             InMemoryProvider (reference implementation).
    store/
        database.py              SQLite connection + user_version migrations.
        serialization.py         Entity <-> row conversion, EventLogEntry.
        store.py                 Store: strict CRUD + append-only event log.
    orchestration/
        policy.py                AssignmentPolicy ABC, FirstAvailablePolicy.
        dispatcher.py            Dispatcher: eligibility, dispatch, session lifecycle.

configs/                       Configuration loading for the Zenith runtime.
    config.py                   Config dataclass and TOML loader.
    config.toml (optional)      User-provided configuration; not required.

shared/                        Infrastructure both applications depend on.
                                Imports neither runtime/ nor engineering_manager/.
    exceptions.py               ZenithError and domain-agnostic exceptions
                                 (incl. EventBusError).
    events/
        event.py                 Event base class.
        bus.py                   EventBus.
        event_logger.py          EventLogger.
    utils/
        time_utils.py            utc_now().
        uuid_utils.py            generate_id().
        fs_utils.py              directory_exists(), file_exists().
        text_utils.py            is_blank_or_padded().

engineering_tools/             Standalone developer utilities, self-contained
                                (no dependency on any other package here).
    watchdog/                   Auto-resumes Claude Code after a session limit.

architecture/                  Architecture Decision Records. See its README.
docs/                          Technical reference documentation (this folder).
plugins/                       Reserved for future Zenith plugin code on disk.
tests/                         pytest suite, one file per module under test
                                (Engineering Manager tests use a test_em_ prefix).
```

## Purpose of each top-level directory

- **runtime/** — the Zenith assistant runtime. Never imports
  `engineering_manager/`.
- **engineering_manager/** — the Engineering Manager. Never imports
  `runtime/` or `configs/`. See `docs/engineering_manager.md`.
- **shared/** — code generic enough for both applications. Anything
  placed here must be reusable by both, not just convenient — see
  ADR 0002 and ADR 0003.
- **configs/** — the Zenith runtime's configuration loading, kept
  separate so "what the config looks like" and "how the app runs" stay
  distinct concerns.
- **engineering_tools/** — standalone developer utilities that can be
  lifted out independently.
- **architecture/** — ADRs: why the system is the way it is.
- **docs/** — reference docs: how the system is built.
- **plugins/** — reserved location for Zenith plugin code loaded from
  disk by a future loader (`docs/plugins.md`); not to be confused with
  `runtime/plugins/`, the framework itself.
- **tests/** — one flat pytest suite covering every package above.
