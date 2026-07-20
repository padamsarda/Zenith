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

The store is **in-memory only** — conversations do not survive a
restart. See Deliberate deferrals.

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
`required`. No type vocabulary until a real integration needs one.

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

Two implementations ship:

- **`EchoProvider`** (`provider_id="echo"`) — echoes the latest user
  message. Registered by `Runtime.start`, so the whole pipeline is
  exercisable before any real integration exists. Not intelligence:
  scaffolding.
- **`ScriptedProvider`** (`provider_id="scripted"`) — plays back a
  fixed sequence of turns and records every brief it received. The
  executable specification and universal test double, the counterpart
  of `InMemoryProvider`.

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
| `CapabilityError` | `CapabilityValidationError`, `ToolRegistrationError`, `ToolNotFoundError`, `SkillRegistrationError`, `SkillNotFoundError` |
| `AssistantError` | `AssistantProviderError`, `AssistantProviderRegistrationError`, `AssistantProviderNotFoundError`, `RequestValidationError` |

## Extending the runtime

| To add… | Do this |
|---|---|
| A tool | Subclass `Tool`, `context.tools.register(tool, context)`. |
| A skill | Subclass `Skill`, `context.skills.register(skill, context)`. |
| A provider | Subclass `AssistantProvider`, `context.assistant_providers.register(provider)`. |
| A permission rule | Subclass `PermissionPolicy`, `context.assistant.set_permission_policy(policy)`. |
| An interception point | Subclass `AssistantHook`, `context.assistant.add_hook(hook)`. |
| An interface | Call `context.assistant.handle(request, context)`. Own nothing else. |

None of these requires an engine, pipeline, or provider change. That is
the point of the milestone.

## Deliberate deferrals

Documented so they read as decisions, not oversights:

- **Durable conversations** — `ConversationStore` is in-memory.
  Persistence is a store implementation behind the same interface; the
  Engineering Manager's SQLite store (ADR 0004) is the proven pattern,
  and briefs are already assembled from durable state, so nothing else
  changes.
- **Real provider integrations** — the contract is proven against
  `ScriptedProvider` and `EchoProvider`; a real adapter implements one
  method.
- **Plugin-contributed capabilities** — `Plugin.register(registry)` is
  where a plugin will contribute tools and skills. It needs the plugin
  *loader* (`docs/plugins.md`), which remains future work; the
  registries it will call already exist.
- **Streaming and concurrency** — synchronous throughout (ADR 0007).
  Both fit behind `handle` when they are needed.
- **Cooperative cancellation** — `RequestStatus.CANCELLED` and
  `CommandContext.cancellation_token` are the reserved places; nothing
  sets either yet.
- **Structured tool results** — tool output is stringified into a
  `TOOL` message. If providers need structure, `Message.metadata` is
  where it goes.
