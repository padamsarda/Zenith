# 0012 — The assistant pipeline: one path from request to reply

- Status: Accepted
- Date: 2026-07-20

## Context

Before this milestone the runtime could start, stop, run a `Command`,
and hold a `Plugin` — but nothing connected "a user said something" to
"Zenith answered." Every future surface (console, voice, GUI, network,
robotics) and every future capability needs that path, and if each
surface builds its own, they diverge immediately: one validates input,
another doesn't; one emits events, another is invisible; one gates
tools, another runs anything a provider asks for.

The command framework (`docs/commands.md`) already established the
principle — every action Zenith performs runs through `CommandExecutor`
so it is validated, timed, logged, and announced. What was missing was
the layer above it: who decides *which* actions to run, using what
context, on whose behalf.

## Decision

One pipeline, `AssistantEngine.handle(request, context)`, is the only
path from a user request to an assistant reply. Every interface calls
it and does nothing else; `ConsoleInterface` is the first, and owns
nothing but line I/O.

The pipeline is a bounded loop:

1. Run `before_request` hooks (a raise rejects the request).
2. Validate the request; resolve its conversation and provider.
3. Record the user message in the conversation.
4. Loop, up to `config.assistant_max_turns`: assemble a `TurnBrief`,
   ask the provider for a turn, validate it, record its text, and
   execute any tool calls it requested. A turn with no tool calls ends
   the request.
5. Run `after_request` hooks (observational; a raise is logged, not
   propagated).

Load-bearing choices inside that shape:

- **Tool calls are Commands.** Each invocation runs through
  `CommandExecutor` (`ToolCallRunner`), inheriting the whole
  validated/timed/logged/evented harness rather than reimplementing
  it. This is what makes "a tool ran" and "a command ran" the same
  observable event on the bus.
- **Tool trouble is data, not failure.** An unknown tool, a permission
  denial, a hook veto, or a raising tool becomes a `TOOL` message the
  provider reads on its next turn. The request continues; the model
  gets to react to what happened, which is the only way it can recover
  or explain.
- **`handle` never raises.** Validation errors, provider bugs, and
  exhausted turn budgets all become a failed `AssistantResponse`,
  mirroring `CommandResult`. A misbehaving provider cannot crash the
  runtime.
- **Two seams, deliberately different.** `PermissionPolicy` is the
  standing rule for what may run (one decision per tool call, the same
  shape as the Engineering Manager's `AssignmentPolicy` and
  `RetryPolicy`). `AssistantHook` is arbitrary code at four
  interception points, where `before_*` may veto and `after_*` may only
  observe. Policies answer "is this allowed?"; hooks do everything
  else.
- **Requests fail; conversations don't.** A failed request leaves its
  conversation `ACTIVE` and usable — the state machines are separate on
  purpose.
- **The engine holds no per-request state.** Everything arrives with
  the call, exactly like `CommandExecutor.execute`, so concurrency
  later is a question about the store, not about the engine.

## Consequences

- A new interface is a thin adapter over `handle`, and inherits
  validation, permissions, hooks, events, and conversation management
  for free.
- A new capability is a registered `Tool`; the pipeline needs no
  changes to expose it, and the provider discovers it through the
  catalog.
- Everything the assistant does is observable on the `EventBus` —
  `RequestReceived`/`Completed`/`Failed` and
  `ToolCallRequested`/`Denied`/`Completed`/`Failed` — so logging, UI,
  and audit are subscriptions, not pipeline changes.
- The turn budget bounds cost and prevents infinite tool loops, at the
  price of failing genuinely long tool chains; `assistant_max_turns` is
  configuration precisely because the right bound is deployment-specific.
- Synchronous throughout, per ADR 0007. Streaming responses and
  concurrent requests will need real design work; nothing here assumes
  they never arrive, and both fit behind `handle`.
