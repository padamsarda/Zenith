# The Assistant Runtime

How Zenith turns "a user said something" into "Zenith answered." This
document covers the conversation model, the capability framework, the
provider abstraction, and the request pipeline that ties them together
— the runtime that assistant features execute inside, not the features
themselves.

For the lifecycle that owns all of this, see `architecture.md`. For the
command framework every tool call runs through, see `commands.md`.

## Overview

```
AssistantRequest        what the user asked (immutable data)
  -> AssistantEngine    the one path from request to reply
       ├─ AssistantHook             interception: before/after request and tool
       ├─ ConversationStore         the conversation being continued
       ├─ AssistantContextAssembler composes the provider's TurnBrief
       │    ├─ CapabilityCatalog     what Zenith can do (tools + skills)
       │    └─ Skill.instructions    active know-how for this request
       ├─ AssistantProvider         produces the next AssistantTurn
       └─ ToolCallRunner            executes requested tools as Commands
            ├─ PermissionPolicy      may this call run?
            └─ CommandExecutor       the validated/timed/logged harness
  -> AssistantResponse   what happened
```

Every interface — the console today, voice or a GUI later — calls
`AssistantEngine.handle` and does nothing else. That is the whole
extension story for surfaces (ADR 0012).

## Conversation model

`runtime/conversation/`.

### Message

`Message` (frozen dataclass) is one immutable entry:

| Field | Type | Description |
|---|---|---|
| `role` | `MessageRole` | `USER`, `ASSISTANT`, `SYSTEM`, or `TOOL`. |
| `content` | `str` | The message text. |
| `metadata` | `dict[str, Any]` | Optional extra data. Defaults to `{}`. |
| `message_id` | `UUID` | Unique per message, auto-generated. |
| `created_at` | `datetime` | UTC, auto-generated. |

`TOOL` marks the recorded outcome of a tool invocation — appended by
the pipeline so the provider sees on its next turn what its requested
calls produced.

Content validation is deliberately looser than identifier validation:
non-empty once stripped, but leading and trailing whitespace is fine.
Message text is prose, and multi-line content legitimately ends in a
newline.

### Conversation

`Conversation` is append-only with a two-state lifecycle:

```
ACTIVE -> ARCHIVED
```

`ARCHIVED` is terminal. An archived conversation stays readable but
accepts no new messages. `messages` returns a snapshot tuple, so no
caller can mutate history from outside, and `state` moves only through
`transition_to` — the same guarantees `Command` and `Plugin` give.

**Requests fail; conversations don't.** A failed request leaves its
conversation `ACTIVE` and usable. The two state machines are separate
on purpose.

### ConversationStore

`context.conversations` is the only path that changes a conversation,
so every change is announced on the `EventBus`:

```python
conversation = store.create(app_context, title="Console session")
store.append(conversation_id, message, app_context)
store.archive(conversation_id, app_context)

store.get(conversation_id)   # -> Conversation, raises ConversationNotFoundError
store.has(conversation_id)   # -> bool, never raises
store.list()                 # -> list[Conversation], a snapshot
```

Mutating methods take the `ApplicationContext` for the same reason
`PluginRegistry`'s do: the store is built via `field(default_factory=…)`
before the rest of the context exists, so it cannot hold a reference to
it.

Events (`source="conversation_store"`): `ConversationStarted`,
`MessageAppended`, `ConversationArchived`.

`ConversationStore` (`runtime/conversation/store.py`) is an ABC with two
implementations (ADR 0018):

- **`InMemoryConversationStore`** — `context.conversations`'s default.
  Conversations do not survive a restart; harmless scaffolding in the
  same role `EchoProvider` plays for assistant providers.
- **`SQLiteConversationStore`** (`runtime/conversation/sqlite/`) — the
  durable one, structured like the Engineering Manager's SQLite store
  (ADR 0004). Not auto-wired: assign an instance onto
  `context.conversations` the same way `ClaudeProvider` (ADR 0015) or a
  `runtime.tools` tool is registered.

Both emit the same events with the same `source`, and — because
`append`/`archive` run the ordinary `Conversation.append`/`transition_to`
on a reconstructed object rather than reimplementing those rules —
reject exactly the same appends and transitions. Any future
`ConversationStore` should do the same: implement persistence, not a
second copy of the domain's validation.

## Capabilities (ADR 0013)

`runtime/capabilities/`. Two kinds, because they are genuinely
different: a tool *acts*, a skill contributes *know-how*.

### Tool

| Member | Kind | Description |
|---|---|---|
| `tool_id` | abstract property | Stable identifier — how providers name it. |
| `name` | abstract property | Display name. |
| `description` | abstract property | What it does; shown to providers. |
| `parameters` | property | `tuple[ToolParameter, ...]`. Defaults to `()`. |
| `invoke(context, arguments)` | abstract | Perform the action, return the result. |

Tools never run themselves. The engine invokes each one inside a
`Command` through `CommandExecutor`, so `context` is that command's
`CommandContext` — which is how a tool reaches the shared
`ApplicationContext`. A raise from `invoke` fails that command, is
reported to the provider as a failed call, and never escapes the
pipeline.

`ToolParameter` is deliberately thin: `name`, optional `description`,
`required`, and `type` (a JSON Schema primitive type name, defaulting to
`"string"`). `type` is the one additive extension made so far — added
for `runtime.providers.claude`, the first real provider integration that
needed a type vocabulary to build tool-call schemas from (ADR 0013,
ADR 0015).

### Skill

| Member | Kind | Description |
|---|---|---|
| `skill_id` | abstract property | Stable identifier — how requests name it. |
| `name` | abstract property | Display name. |
| `description` | abstract property | What it teaches. |
| `instructions(request)` | abstract | Text contributed to the provider's brief. |
| `applies_to(request)` | method | Automatic activation. Defaults to `False`. |

A skill is active for a request when the request names it in
`metadata["skills"]`, or its own `applies_to` opts in. Active skills'
instructions are composed into the brief, ordered by skill ID.

`instructions` **must be deterministic** for a given request — briefs
must be reproducible from the same state (ADR 0010's principle applied
to assistant behavior).

### Built-in tools (ADR 0016)

`runtime/tools/` holds concrete `Tool` implementations, parallel to how
`runtime/providers/` holds concrete `AssistantProvider`s alongside the
abstract contract in `providers/base.py`. Every one runs through the
ordinary pipeline — `ToolRegistry`, `CommandExecutor`, `PermissionPolicy`,
`AssistantHook` — with no engine change, and none is auto-registered:
like `ClaudeProvider`, an integrator constructs each with the sandbox
root(s) its deployment allows and registers it explicitly.

| Tool | `tool_id` | What it does |
|---|---|---|
| `FilesystemTool` | `filesystem` | `read`/`write`/`list`/`mkdir`/`delete`/`exists`, sandboxed to a root directory. |
| `ShellTool` | `shell` | Runs one shell command line with configurable `cwd` (sandboxed), `env`, and `timeout_seconds`. |
| `GitTool` | `git` | `status`/`diff`/`add`/`commit`/`branch`/`checkout`/`log`/`reset` (mixed mode only) against a repository. No `push`, `pull`, `clone`, or `--hard`. |
| `DiffTool` | `diff` | A unified diff (`difflib`) between two inline texts or two sandboxed files. |
| `TestRunnerTool` | `test_runner` | Runs the test suite (`python -m pytest` by default) and reports the exit code, captured output, and best-effort pass/fail counts. |

`FilesystemTool`, `ShellTool` (`cwd`), `GitTool` (path arguments), and
`TestRunnerTool` (`path`) all confine their path arguments to a
configured root through `runtime.tools.sandbox.resolve_within_root`, one
guard shared by every one of them rather than five slightly different
checks. `ShellTool`, `GitTool`, and `TestRunnerTool` shell out through
`runtime.tools.process.run_process`, which enforces a timeout and checks
`CommandContext.cancellation_token` — raising `CommandCancelledError` if
it is set — the reserved seam `docs/commands.md` describes, now with its
first real user.

Registering one:

```python
from pathlib import Path

from runtime.assistant.permissions import ToolAllowlistPolicy
from runtime.tools.filesystem import FilesystemTool
from runtime.tools.git import GitTool

project_root = Path("/path/to/project")
context.tools.register(FilesystemTool(project_root), context)
context.tools.register(GitTool(project_root), context)
context.assistant.set_permission_policy(
    ToolAllowlistPolicy(["filesystem", "git"])
)
```

`ToolAllowlistPolicy` (see Permissions and hooks, below) is the real
`PermissionPolicy` this tool suite calls for — `AllowAllPolicy` is no
longer honest once a registered tool can act on the world.

### Registries and the catalog

`ToolRegistry` (`context.tools`) and `SkillRegistry` (`context.skills`)
mirror `ServiceRegistry`: explicit `register`/`unregister`/`get`/`has`/
`list`, validation at the boundary, events on the bus, no discovery.
Both take the `ApplicationContext` on mutating calls, like
`PluginRegistry`.

Events: `ToolRegistered`/`ToolUnregistered` (`source="tool_registry"`),
`SkillRegistered`/`SkillUnregistered` (`source="skill_registry"`).

`build_catalog(tools, skills)` produces a `CapabilityCatalog` of
immutable `CapabilityDescriptor`s — the single discovery surface.
Providers receive descriptors, never the objects, so nothing can invoke
a tool outside the pipeline. Descriptors are sorted by capability ID,
so identical registrations yield identical catalogs regardless of
registration order, and the catalog is built on demand and never
cached, so it cannot go stale.

## Provider abstraction (ADR 0011)

`runtime/providers/base.py` is the entire vocabulary the runtime speaks
to any assistant AI:

```python
turn = provider.generate_turn(brief)   # TurnBrief -> AssistantTurn
```

| Type | Purpose |
|---|---|
| `TurnBrief` | Conversation ID, message history, composed `instructions`, `CapabilityCatalog`, `metadata`. |
| `AssistantTurn` | `text`, `tool_calls`, or both. |
| `ToolCall` | `tool_id`, `arguments`, and a `call_id` linking the result back. |

A turn with neither text nor tool calls is invalid and the engine
rejects it. Implementations must fail honestly —
`AssistantProviderError`, never an empty turn. Credentials are resolved
inside the implementation, never stored by the runtime.

This is **not** the Engineering Manager's `Provider` (ADR 0005). That
contract's unit of work is a long-running engineering session (start,
check, resume, stop); this one's is a single turn. ADR 0011 records why
they stay separate.

`AssistantProviderRegistry` (`context.assistant_providers`) mirrors the
Engineering Manager's `ProviderRegistry`: explicit register/get/has/
list, and — like it — no events, since providers are wired once at
startup rather than churning as the runtime runs.

Implementations that ship:

- **`EchoProvider`** (`provider_id="echo"`) — echoes the latest user
  message. Registered by `Runtime.start`, so the whole pipeline is
  exercisable before any real integration exists. Not intelligence:
  scaffolding.
- **`ScriptedProvider`** (`provider_id="scripted"`) — plays back a
  fixed sequence of turns and records every brief it received. The
  executable specification and universal test double, the counterpart
  of `InMemoryProvider`.
- **`ClaudeProvider`** (`provider_id="claude"`, `runtime/providers/claude.py`)
  — the first real integration (ADR 0015), calling the Anthropic
  Messages API directly over `urllib` (standard library only; no
  `anthropic` SDK dependency). Not wired in automatically like
  `EchoProvider`; register it explicitly where credentials are
  available:

  ```python
  from runtime.providers.claude import ClaudeProvider

  context.assistant_providers.register(ClaudeProvider())  # reads ANTHROPIC_API_KEY
  ```

  Split across three modules by responsibility: `claude_transport.py`
  (stdlib HTTP, retries, timeouts, streaming), `claude_messages.py`
  (conversation and tool-call translation, including the `ToolCallCache`
  that reconstructs `tool_use`/`tool_result` pairs across turns), and
  `claude.py` (the `AssistantProvider` itself: request composition, usage
  accounting, logging). `ClaudeProvider.usage` exposes cumulative token
  counts; nothing in the pipeline consumes it yet, but it is there to
  inspect or log downstream.

## The request pipeline (ADR 0012)

### AssistantRequest

| Field | Type | Description |
|---|---|---|
| `conversation_id` | `UUID` | The conversation to continue. |
| `text` | `str` | What the user said. |
| `metadata` | `dict[str, Any]` | Request-scoped extension point. |
| `request_id` | `UUID` | Unique, auto-generated. |
| `created_at` | `datetime` | UTC, auto-generated. |
| `status` | `RequestStatus` | Defaults to `RECEIVED`. |

Two metadata keys are understood by the pipeline: `"provider"` (a
provider ID overriding the configured default) and `"skills"` (skill
IDs to activate).

`status` moves only through `transition_to`, like `Command.status`:

```
RECEIVED -> RUNNING -> COMPLETED
        \--------> FAILED / CANCELLED
```

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal. `CANCELLED` is
reserved for a future cancellation mechanism, mirroring
`CommandStatus.QUEUED`.

### AssistantResponse

What `handle` always returns — never `None`, mirroring `CommandResult`:

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Whether the request produced a reply. |
| `text` | `str` | The reply, or the failure explanation. |
| `request_id` / `conversation_id` | `UUID` | What this answers. |
| `duration_seconds` | `float` | Wall-clock, via `perf_counter()`. |
| `turns` | `int` | How many provider turns it took. |
| `exception` | `BaseException \| None` | The cause, when one exists. |

### Execution flow

`AssistantEngine.handle(request, application_context)`:

1. Emit `RequestReceived`.
2. Run `before_request` hooks — a raise rejects the request.
3. `validate_request`, resolve the conversation, resolve the provider
   (`metadata["provider"]`, else `config.assistant_provider`).
4. Transition to `RUNNING`; record the user message.
5. Loop, bounded by `config.assistant_max_turns`:
   - Assemble a `TurnBrief`; call `provider.generate_turn`;
     `validate_turn`.
   - Record the turn's text, if any, as an `ASSISTANT` message.
   - **No tool calls: the request is complete.** Emit
     `RequestCompleted`, return a successful response.
   - Otherwise run each tool call, then loop.
6. Exhausting the turn budget fails the request.
7. Run `after_request` hooks on every outcome; a raise is logged, not
   propagated.

`handle` **never raises**. Validation errors, provider bugs, unknown
providers, and exhausted budgets all become a failed
`AssistantResponse`. The engine holds no per-request state — everything
arrives with the call, exactly like `CommandExecutor.execute`.

### Tool calls

`ToolCallRunner` executes one call:

1. Emit `ToolCallRequested`.
2. Resolve the tool. Unknown -> `ToolCallFailed`.
3. `PermissionPolicy.evaluate`. Denied -> `ToolCallDenied`.
4. `before_tool` hooks. A raise -> `ToolCallDenied`.
5. Execute as a `Command` named `tool.<tool_id>` through
   `CommandExecutor` -> `ToolCallCompleted` or `ToolCallFailed`.
6. `after_tool` hooks; a raise is logged, not propagated.

**Every outcome is recorded as a `TOOL` message and the request
continues.** An unknown tool, a denial, a veto, or a raising tool is
information the model reads on its next turn and can react to — not a
reason to abandon the request. This is why nothing here fails the
request.

### Context assembly

`AssistantContextAssembler` composes each `TurnBrief` from durable
state: the conversation's messages, the active skills' instructions,
and a freshly built `CapabilityCatalog`. Nothing is cached or stored,
so a brief can never go stale, and it survives restarts by construction
once conversations are durable. This is ADR 0010's principle applied to
the assistant.

### Permissions and hooks

`PermissionPolicy` (`runtime/assistant/permissions.py`) is the standing
rule for what may run — one `PermissionDecision` per tool call. The
default `AllowAllPolicy` permits everything, which is honest while only
harmless tools exist. It is the same policy seam the Engineering
Manager uses for assignment and retry: replace the class, change
nothing else.

```python
context.assistant.set_permission_policy(MyPolicy())
```

`ToolAllowlistPolicy` ships alongside the built-in tools (ADR 0016): it
permits only the `tool_id`s named at construction and denies everything
else, with a reason recorded in the conversation.

```python
context.assistant.set_permission_policy(ToolAllowlistPolicy(["filesystem", "git"]))
```

Per-tool user confirmation is not built — a `before_tool`
`AssistantHook` is the seam for it, not a new mechanism.

`AssistantHook` (`runtime/assistant/hooks.py`) is arbitrary code at
four points. The two kinds differ deliberately:

| Method | May veto? | When |
|---|---|---|
| `before_request` | Yes, by raising | Before a request is served. |
| `before_tool` | Yes, by raising | Before a permitted tool call runs. |
| `after_request` | No — logged | After a request finishes, every outcome. |
| `after_tool` | No — logged | After a tool call runs, every outcome. |

`before_*` can stop things happening; that is what distinguishes hooks
from event listeners, which can only observe. `after_*` observes
something that already happened, so a raise there is suppressed exactly
like a failing `EventBus` listener.

```python
context.assistant.add_hook(MyHook())   # hooks run in the order added
```

### Events

All emitted with `source="assistant_engine"`:

- `RequestReceived` — `request_id`, `conversation_id`.
- `RequestCompleted` — `request_id`, `duration_seconds`, `turns`.
- `RequestFailed` — `request_id`, `reason`.
- `ToolCallRequested` — `request_id`, `call_id`, `tool_id`.
- `ToolCallDenied` — plus `reason`.
- `ToolCallCompleted` — plus `duration_seconds`.
- `ToolCallFailed` — plus `reason`.

Because tool calls run as commands, every one also produces the usual
`CommandCreated`/`Started`/`Completed`|`Failed` events. Logging, UI,
and audit are subscriptions, not pipeline changes.

## The console

`runtime/console.py` is the first interface and the model for every
future one: it owns nothing but line I/O. Each line becomes an
`AssistantRequest`, served by `context.assistant`, inside one
conversation created at session start and archived on the way out —
whatever ends the session.

```toml
# configs/config.toml
interactive = true
```

```
$ python main.py
you> hello
zenith> You said: hello
you> exit
```

Streams are injectable, so tests drive a whole session through
`io.StringIO` with no terminal.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `interactive` | `false` | Serve a console session instead of idling. |
| `assistant_provider` | `"echo"` | Provider used when a request names none. |
| `assistant_max_turns` | `8` | Provider turns one request may take. |

Validated in `runtime/validation.py` like every other config field. The
configured default may name a provider registered later — resolution
happens per request, not at startup.

## Exceptions

Added to `runtime.exceptions`, all rooted at `ZenithError`:

| Base | Subclasses |
|---|---|
| `ConversationError` | `ConversationNotFoundError`, `ConversationValidationError` |
| `CapabilityError` | `CapabilityValidationError`, `ToolRegistrationError`, `ToolNotFoundError`, `SkillRegistrationError`, `SkillNotFoundError`, `ToolExecutionError` |
| `AssistantError` | `AssistantProviderError`, `AssistantProviderRegistrationError`, `AssistantProviderNotFoundError`, `RequestValidationError` |

`ToolExecutionError` is raised by a built-in tool's own guards (a path
escaping its sandbox root, a missing git repository, a subprocess that
failed to start) — see ADR 0016.

## Extending the runtime

| To add… | Do this |
|---|---|
| A tool | Subclass `Tool`, `context.tools.register(tool, context)`. `runtime/tools/` holds the built-in ones (ADR 0016). |
| A skill | Subclass `Skill`, `context.skills.register(skill, context)`. |
| A provider | Subclass `AssistantProvider`, `context.assistant_providers.register(provider)`. |
| A permission rule | Subclass `PermissionPolicy`, `context.assistant.set_permission_policy(policy)`. |
| An interception point | Subclass `AssistantHook`, `context.assistant.add_hook(hook)`. |
| An interface | Call `context.assistant.handle(request, context)`. Own nothing else. |

None of these requires an engine, pipeline, or provider change. That is
the point of the milestone.

## Deliberate deferrals

Documented so they read as decisions, not oversights:

- **Durable conversations** — shipped: `ConversationStore` is now an ABC
  (`runtime/conversation/store.py`), `InMemoryConversationStore` is the
  unchanged default, and `SQLiteConversationStore`
  (`runtime/conversation/sqlite/`, ADR 0018) is the durable backend, an
  integrator assigns onto `context.conversations` the same way a
  `runtime.tools` tool is registered. Testing it against the real
  pipeline (not just its own tests) found a real bug in
  `AssistantEngine.handle` — it held a `conversation` reference across
  the whole turn loop, which only worked because the in-memory store's
  `get()` happens to return a live, shared-mutation object. Fixed by
  re-fetching every turn, which is what ADR 0010's "assembled from
  durable state, never cached" already claimed should happen.
- **Real provider integrations** — shipped: `ClaudeProvider` (ADR 0015)
  implements the one method (`generate_turn`) the contract asks for. A
  second real integration remains the next pressure test of the
  contract's provider-agnosticism.
- **Plugin-contributed capabilities** — shipped: `PluginLoader`
  (ADR 0017, `docs/plugins.md`) discovers `plugin.py` files under
  `plugins/` and registers them at `Runtime.start()`.
  `plugins/engineering_workflow/` is the first plugin loaded this way,
  and ships the first genuine `Skill` (`EngineeringWorkflowSkill`) —
  `Plugin.register(registry)` is now the real distribution mechanism
  ADR 0013 described, not a hook nothing calls. A plugin that
  contributes a `Tool` rather than a `Skill` is the next pressure test:
  it would be free to act under whatever `PermissionPolicy` is
  configured (`AllowAllPolicy` by default), which auto-loading a
  skill-only plugin deliberately sidesteps.
- **Streaming and concurrency** — synchronous throughout (ADR 0007).
  Both fit behind `handle` when they are needed.
- **Cooperative cancellation** — `RequestStatus.CANCELLED` is still
  unused, but `CommandContext.cancellation_token` has its first real
  reader: `runtime.tools.process.run_process` (ADR 0016) checks it
  before and during every subprocess it runs and raises
  `CommandCancelledError` if it is set. Nothing yet *sets* a token to
  `cancelled` mid-flight — it is immutable once constructed — so this
  is forward-looking today, directly testable by constructing a
  pre-cancelled `CommandContext` and calling `invoke` directly.
- **Structured tool results** — tool output is still stringified into a
  `TOOL` message; the built-in tools' result dataclasses
  (`FilesystemResult`, `ShellResult`, `GitResult`, `DiffResult`,
  `TestRunResult`) define `__str__` accordingly. If providers need
  structure, `Message.metadata` is where it goes.
