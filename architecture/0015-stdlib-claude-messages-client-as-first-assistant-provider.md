# 0015 — A stdlib-only Claude Messages API client as Zenith's first real AssistantProvider

- Status: Accepted
- Date: 2026-07-20

## Context

ADR 0011 defined `AssistantProvider` against `ScriptedProvider` and
`EchoProvider` alone; a real integration was roadmap item one for the
runtime, expected to answer two open questions the ADR deferred: whether
`ToolParameter` needs a real type vocabulary, and what a genuine
turn-producing implementation demands of the contract. The repository's
dependency policy is standard library only — the `anthropic` SDK is not
an option without an ADR admitting a new dependency, which this one
does not do. Separately, the turn contract has a structural gap a real
provider exposes immediately: the pipeline records a tool call's
*outcome* as a `TOOL` message (ADR 0012) but never the call itself, while
the Messages API requires every `tool_use` block to be answered by a
`tool_result` block sharing its ID, within the same (stateless) request.

## Decision

`ClaudeProvider` (`runtime/providers/claude.py`, with two siblings)
calls `https://api.anthropic.com/v1/messages` directly over
`urllib.request` — no SDK, per the standard-library-only policy:

- **`claude_transport.py`** builds and sends the HTTP request: retries
  on 429/5xx (`RETRYABLE_STATUS_CODES`) with exponential backoff or the
  server's `retry-after`, raises `AssistantProviderError` on a
  non-retryable status or exhausted retries, and normalizes both a plain
  JSON response and a server-sent-events stream into one shape via
  `claude_stream.consume_event_stream`, so the rest of the provider reads
  one response format regardless of transport mode. `stream` is exposed
  but defaults off: Anthropic recommends it for large `max_tokens` to
  avoid one long blocking read, but a reference implementation should
  default to the simplest correct path.
- **`claude_messages.py`** converts `TurnBrief.messages` into Claude's
  `messages` array plus a `system` string, and `CapabilityCatalog` tool
  descriptors into Claude's tool JSON schema. It also closes the
  tool-call gap entirely inside the provider, with no pipeline or
  conversation-model change: `ToolCallCache` remembers every `ToolCall`
  this provider issues, keyed by its own freshly generated `call_id` (a
  UUID `ToolCall.call_id` requires; Claude's own string `tool_use` ID is
  discarded and never needed again, because each request is
  self-contained — only *this* request's `tool_use`/`tool_result` IDs
  must agree with each other, not with anything from an earlier,
  separate call). A batch of tool calls from one turn is replayed
  together as one assistant message's `tool_use` blocks and one user
  message's `tool_result` blocks, since Claude requires a turn's tool
  calls resolved as a unit. An unknown `call_id` (a different provider's
  call, or one this cache has evicted) degrades gracefully to a
  synthetic single-call block with no remembered arguments — still valid
  API shape, honestly less faithful, never a broken request.
- **`ClaudeProvider`** composes the request, sends it, translates the
  response back into an `AssistantTurn`, and raises
  `AssistantProviderError` if neither text nor tool calls come back —
  the contract's honesty requirement, never an empty turn.

Two small, additive changes to the existing contract follow directly
from building this for real, both anticipated by their originating ADRs
rather than invented here:

- **`ToolParameter` gains `type: str = "string"`.** ADR 0013 left
  parameters deliberately thin "until a real integration needs one";
  this is that integration, and the field is the minimum needed to build
  a JSON Schema `properties` entry per parameter. The default preserves
  every existing declaration's current meaning.
- **`ProviderSessionStatus` (the *Engineering Manager's* contract, ADR
  0005) gains `usage`, in the sibling `ClaudeCodeProvider` (ADR 0014) —
  noted here only because it is the same "additive by design" pattern
  applied on both sides of the repository at once.

Authentication resolves an API key at construction (`api_key=`, else
`ANTHROPIC_API_KEY`), raising `AssistantProviderError` immediately if
neither is present — credentials are resolved inside the implementation
and never stored by the runtime, per ADR 0011.

## Consequences

- The engine and pipeline needed zero changes: `generate_turn` is still
  the provider's only obligation, and the tool-call round-trip problem
  is solved entirely behind that one method.
- `ToolCallCache` is in-memory and bounded (oldest batches evicted past
  a configurable limit); a process restart or a very long conversation
  both degrade to the same graceful, documented fallback, never an
  error — the same category of deferral `ConversationStore` already
  accepts.
- Turns are stateless HTTP calls: there is no server-side "session" to
  create, check, or resume on the assistant side, unlike the Engineering
  Manager's `Provider`. This is ADR 0011's distinction holding exactly as
  predicted, not a new design decision.
- Usage accounting (`ClaudeProvider.usage`) and truncation warnings
  (`stop_reason == "max_tokens"`) are logged and exposed for inspection;
  nothing in the pipeline consumes them yet, which is fine — they are
  observable the same way command and event-bus data already is.
- A second real assistant integration remains the next pressure test of
  the contract's provider-agnosticism, unaffected by anything decided
  here.
