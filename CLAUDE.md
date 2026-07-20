# CLAUDE.md

Guidance for AI systems (and new humans) working in this repository.

## What this repository is

Two applications over one shared foundation (ADR 0002):

- `runtime/` — the **Zenith** assistant runtime (lifecycle, events,
  commands, plugins, and the assistant subsystem: conversations,
  capabilities, providers, and the request pipeline). Entry point:
  `python main.py`.
- `engineering_manager/` — the **Engineering Manager**, a local-first
  orchestrator of AI-performed engineering work (projects, plans,
  tasks, sessions, providers, and the execution engine that drives
  them). Entry point: `python -m engineering_manager`.
- `shared/` — the only code both may import (exceptions, event system,
  utilities).

Hard boundary: `engineering_manager/` never imports `runtime/` or
`configs/`; `runtime/` never imports `engineering_manager/`; `shared/`
imports neither.

## Commands

```bash
pip install -e ".[dev]"   # once
pytest                    # full suite; must be green before any commit
pytest tests/test_em_store.py -q   # one module while iterating
```

## Before writing code

1. `docs/conventions.md` — style, structure, error, and test rules.
   They are followed strictly; match the existing code exactly.
2. `architecture/README.md` and the ADR index — do not contradict an
   accepted ADR; supersede it with a new one if it must change.
3. The reference doc for the area you touch: `docs/architecture.md`
   (runtime), `docs/assistant.md` (the assistant subsystem),
   `docs/engineering_manager.md` (EM), `docs/events.md`,
   `docs/commands.md`, `docs/plugins.md`.
4. `docs/roadmap.md` — the intended build order; prefer roadmap items
   over invented scope.

## Non-negotiables (short version)

- Standard library only; `pytest` is the sole dev dependency. Adding
  anything else requires an ADR.
- One responsibility per file; split near ~250 lines.
- Every raised error subclasses `ZenithError`. Validation is guard
  functions that raise; construction never validates.
- Domain state changes only through `transition_to` against an explicit
  transition table. Frozen dataclasses for data, controlled mutators
  for the exceptions.
- No module-level mutable globals, no decorators-as-registration, no
  magic. Registries are explicit method calls.
- One test file per source module (`test_em_` prefix for Engineering
  Manager modules); tests use `tmp_path`, never the real project tree,
  and never share mutable fixtures.
- Store schema changes are **append-only migrations** in
  `engineering_manager/store/database.py` — never edit a shipped
  migration.
- Keep docs in `docs/` and the ADR index truthful in the same change
  that alters behavior.

## Extension recipes

- **New provider integration**: subclass
  `engineering_manager.providers.base.Provider` (four methods), treat
  `InMemoryProvider` + `tests/test_em_in_memory_provider.py` as the
  executable spec, register via `ProviderRegistry`. Credentials are
  resolved inside your implementation, never stored in the EM. All
  orchestration decisions (resume timing, retries, assignment) belong
  to the `ExecutionEngine` and its policy seams — providers only
  report facts.
- **New assignment policy**: subclass
  `engineering_manager.orchestration.policy.AssignmentPolicy`; the
  dispatcher needs no changes.
- **New retry policy**: subclass
  `engineering_manager.orchestration.retry.RetryPolicy`; the engine
  needs no changes. Attempt counts derive from session history — never
  store them.
- **New EM event**: add the type to `engineering_manager/events.py`,
  publish through the facade/dispatcher/engine `_publish` path so it
  reaches both the event log and the bus, and extend
  `tests/test_em_events.py`.
- **New engine behavior**: keep it inside `tick()` (a phase, or logic
  within one) so it stays deterministic and clock-injectable;
  `run()` must remain nothing but tick-on-an-interval (ADR 0008).
- **New runtime capability**: execute it as a `Command` through
  `CommandExecutor`; new shared state lives on `ApplicationContext`.
- **New Zenith plugin**: subclass `runtime.plugins.plugin.Plugin`;
  lifecycle is driven by `PluginRegistry` (`docs/plugins.md`).
- **New assistant tool**: subclass `runtime.capabilities.tool.Tool`
  (four members), register via `ToolRegistry`. The engine invokes it as
  a `Command`, so never call it directly and never gate it yourself —
  that is the `PermissionPolicy`'s job (ADR 0013).
- **New assistant skill**: subclass `runtime.capabilities.skill.Skill`;
  `instructions(request)` must be deterministic, or briefs stop being
  reproducible (ADR 0010's principle, applied in ADR 0013).
- **New assistant provider**: subclass
  `runtime.providers.base.AssistantProvider` (one method), treat
  `ScriptedProvider` + `tests/test_provider_scripted.py` as the
  executable spec, register via `AssistantProviderRegistry`.
  Credentials are resolved inside your implementation, never stored in
  the runtime. Providers report turns; every decision about *what to
  do* with a turn belongs to the `AssistantEngine` (ADR 0011).
- **New permission rule**: subclass
  `runtime.assistant.permissions.PermissionPolicy`; the engine needs no
  changes.
- **New cross-cutting behavior** (auditing, budgets, confirmation):
  subclass `runtime.assistant.hooks.AssistantHook`. `before_*` may veto
  by raising; `after_*` may only observe.
- **New assistant event**: add the type to
  `runtime/assistant/events.py`, emit it from the engine or the tool
  runner, and extend `tests/test_assistant_events.py`.
- **New user-facing interface** (voice, GUI, network): call
  `context.assistant.handle(request, context)` and own nothing else —
  `runtime/console.py` is the model (ADR 0012).
