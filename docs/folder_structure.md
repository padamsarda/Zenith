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
    console.py                  ConsoleInterface: interactive text session.
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
    conversation/
        message.py               Message, MessageRole.
        state.py                 ConversationState enum, TERMINAL_STATES.
        validation.py            Conversation validation guard functions.
        conversation.py          Conversation (append-only message history).
        events.py                Concrete conversation events.
        store.py                 ConversationStore.
    capabilities/
        tool.py                  Tool (ABC), ToolParameter.
        skill.py                 Skill (ABC).
        validation.py            Capability validation guard functions.
        events.py                Concrete capability registry events.
        tool_registry.py         ToolRegistry.
        skill_registry.py        SkillRegistry.
        catalog.py               CapabilityCatalog, CapabilityDescriptor, build_catalog.
    providers/
        base.py                  AssistantProvider ABC, TurnBrief,
                                  AssistantTurn, ToolCall.
        registry.py              AssistantProviderRegistry.
        echo.py                  EchoProvider (built-in default).
        scripted.py              ScriptedProvider (reference implementation).
    assistant/
        status.py                RequestStatus enum, TERMINAL_STATUSES.
        validation.py            Request and turn guard functions.
        request.py               AssistantRequest.
        response.py              AssistantResponse.
        events.py                Concrete assistant pipeline events.
        permissions.py           PermissionPolicy ABC, AllowAllPolicy.
        hooks.py                 AssistantHook.
        assembler.py             AssistantContextAssembler: composes TurnBriefs.
        tool_runner.py           ToolCallRunner: executes one tool call.
        engine.py                AssistantEngine: the request pipeline.

engineering_manager/           The Engineering Manager application.
    __init__.py                 Package docstring only.
    __main__.py                 `python -m engineering_manager` entry point.
    cli.py                      Command-line interface over the facade.
    manager.py                  EngineeringManager facade.
    events.py                   Concrete Engineering Manager events.
    exceptions.py               EM exception hierarchy (rooted at ZenithError).
    domain/
        states.py                ProjectStatus, PlanStatus, TaskStatus,
                                  SessionStatus + terminals.
        validation.py            Structural and transition guard functions.
        project.py               Project.
        plan.py                  Plan.
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
        retry.py                 RetryPolicy ABC, LimitedRetryPolicy.
        graph.py                 Dependency-graph analysis: cycles, waves, blockages.
        context.py               ContextAssembler: composes session briefs.
        plans.py                 PlanCoordinator: plan lifecycle operations.
        dispatcher.py            Dispatcher: eligibility, dispatch, session lifecycle.
        engine.py                ExecutionEngine: the reconcile-and-advance tick.

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
