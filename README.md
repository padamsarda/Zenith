# Zenith

This repository hosts two applications built on one shared foundation:

- **Zenith** (`runtime/`) — a runtime platform for building and
  operating an assistant called **Zeni**. It provides lifecycle
  management, an event system, a command execution framework, a plugin
  framework, and the assistant runtime itself: conversations,
  tool/skill capabilities, a provider-independent AI contract, and the
  request pipeline every interface serves requests through. Assistant
  capabilities land on top of these.
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
  service registry, command framework, plugin framework, the assistant
  subsystem (`conversation/`, `capabilities/`, `providers/`,
  `assistant/`), the console interface, and the runtime's own event
  types.
- **engineering_manager/** — the Engineering Manager: domain model
  (projects, plans, tasks, sessions, accounts), provider abstraction,
  SQLite persistence with an event log, the execution engine, and a
  CLI.
- **shared/** — infrastructure both applications use: base exceptions,
  the event system (`shared/events/`), and small utilities.
- **configs/** — configuration loading for the Zenith runtime.
- **engineering_tools/** — standalone developer utilities (e.g.
  `watchdog/`, which auto-resumes Claude Code after a session limit).
- **architecture/** — Architecture Decision Records. Start with
  [`architecture/README.md`](architecture/README.md).
- **docs/** — technical reference documentation.
- **plugins/** — Zenith plugins, auto-discovered and loaded at startup
  (`PluginLoader`, ADR 0017). `plugins/engineering_workflow/` is the
  first one, and ships the first genuine assistant `Skill`.
- **tests/** — pytest suite, one file per source module.

## Requirements

- Python 3.12+ (standard library only; `pytest` is the sole
  development dependency)

## Running Zenith

```bash
python main.py
```

Prints a startup banner, verifies the project layout, loads
configuration (defaults if `configs/config.toml` is absent), registers
the built-in assistant provider, and idles until Ctrl+C shuts it down
gracefully.

For an interactive session, set `interactive = true` in
`configs/config.toml`:

```
$ python main.py
you> hello
zenith> You said: hello
you> exit
```

The built-in `EchoProvider` is scaffolding, not intelligence — it
exists so the whole pipeline is exercisable before a real provider is
integrated. Swapping in a real one is configuration
(`assistant_provider`), not a code change. See
[`docs/assistant.md`](docs/assistant.md).

### Running Zeni for real

With `ANTHROPIC_API_KEY` set, `main.py` also registers `ClaudeProvider`,
a tool suite (filesystem, shell, git, diff, test runner, and the desktop
control tools below), and a `ConfirmationHook` that asks on the console
before any destructive call (`shell`, or `filesystem`'s `write`/
`delete`) actually runs — see [ADR 0025](architecture/0025-main-as-composition-root-with-confirmed-destructive-tools.md).
Set `assistant_provider = "claude"` and `interactive = true` in
`configs/config.toml` to actually talk to it:

```
$ ANTHROPIC_API_KEY=sk-... python main.py
you> open spotify
zenith> Opened Spotify.
you> pause the music
zenith> Sent play_pause x1.
```

Opening applications and controlling media/volume by name
([ADR 0024](architecture/0024-desktop-control-the-first-os-acting-tools.md))
runs unconfirmed — neither can lose data.

Zeni also **remembers**
([ADR 0027](architecture/0027-memory-automatic-recall-recency-importance-relevance.md)):
substantive things you tell it are stored durably in `~/.zenith/memory.db`
and recalled automatically into every turn, scored by recency,
importance, and relevance, with relative time ("yesterday", "last
month") resolved to real dates. Device commands are deliberately not
remembered. See [`docs/memory.md`](docs/memory.md).

```
you> The CubeSat battery is an 18650 lithium pack
zenith> Noted.
you> exit

$ python main.py          # a new session, days later
you> what battery does the cubesat use
zenith> An 18650 lithium pack.
```

## Running the Engineering Manager

One objective, from a sentence to a finished, reviewed, reported change:

```bash
python -m engineering_manager project add zenith "Zenith" --path .
python -m engineering_manager workflow zenith "Add a --json flag to status" \
    --account personal --verify-command "python -m pytest"
```

`workflow` runs the whole lifecycle: a provider decomposes the goal into
a task graph, you approve it, the engine executes it — dispatching,
retrying, resuming after provider limits, and verifying each claimed
completion — you accept the finished work, and a Markdown engineering
report is written beside the database. Ctrl+C is safe at any point;
`workflow zenith --resume <plan-id>` picks up where it stopped.

To watch the entire lifecycle right now, with no subscription, network,
or API key — the engineering sessions are simulated, the orchestration
is real:

```bash
python -m engineering_manager --db /tmp/demo.db project add demo "Demo" --path .
python -m engineering_manager --db /tmp/demo.db \
    workflow demo "Add a health check endpoint" \
    --provider in-memory --interval 0 --yes --accept
```

Every step is also a command of its own (`plan from-goal`, `plan
approve`, `run --until quiescent`, `plan accept`, `project report`) for
when you want to stop between them. State persists in
`~/.zenith/engineering_manager.db` (override with `--db`).

Start with [`docs/workflow.md`](docs/workflow.md) — the lifecycle end to
end. Then [`docs/engineering_manager.md`](docs/engineering_manager.md)
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
CI (`.github/workflows/ci.yml`) runs this same gate against Python 3.12
and 3.13 on every push to `master` and every pull request.

## Further reading

- [`docs/workflow.md`](docs/workflow.md) — the engineering lifecycle end to end: project, plan, execution, verification, reporting.
- [`docs/architecture.md`](docs/architecture.md) — Zenith runtime internals.
- [`docs/assistant.md`](docs/assistant.md) — the assistant runtime: conversations, capabilities, providers, and the request pipeline.
- [`docs/memory.md`](docs/memory.md) — Zeni's long-term memory: what it stores, how it recalls, and what it deliberately does not remember.
- [`docs/reflection.md`](docs/reflection.md) — what Zeni concludes from what it remembers: three levels of reflection, with provenance back to the evidence.
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
