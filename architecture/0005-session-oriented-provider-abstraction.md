# 0005 — A session-oriented, provider-agnostic provider contract

- Status: Accepted
- Date: 2026-07-20

## Context

The Engineering Manager must coordinate many AI providers (Claude,
Gemini, Codex, OpenRouter, Cerebras, future cloud and local models),
several accounts per provider, and long-running work that hits provider
session limits and must be resumed — the exact problem
`engineering_tools/watchdog` solves manually today. A project principle
forbids designing around any specific provider. The temptation is to
model providers richly (chat APIs, streaming, tool use); the risk is an
interface invented ahead of any real integration that the first real
integration then invalidates.

## Decision

Model exactly what orchestration needs and nothing more
(`engineering_manager/providers/base.py`):

- `Provider` is an ABC with four operations: `start_session(spec)`,
  `check_session(handle)`, `resume_session(handle)`,
  `stop_session(handle)`.
- Work is described by a `SessionSpec` (project, task, account, model,
  instructions, plus a `metadata` dict as the provider-specific
  extension point) and referenced by an opaque `SessionHandle`
  (`external_ref`), which a resume may replace.
- `check_session` returns one of five states; `LIMIT_REACHED` (with an
  optional `resume_at`) is first-class and distinct from `FAILED`,
  because it is the one interruption the orchestrator must recover from
  automatically.
- Accounts are data (`ProviderAccount`), not classes. Credentials are
  never stored by the Engineering Manager; each provider implementation
  resolves its own from the account ID.
- `InMemoryProvider` is the executable specification of the contract
  and the test double for all orchestration tests.

## Consequences

- The dispatcher and policies are provably provider-agnostic: they are
  fully tested with no real provider in the repository.
- Real integrations (first candidate: a CLI-driven Claude Code adapter
  generalizing the watchdog) implement four methods and inherit all
  orchestration behavior.
- The contract will grow additively (capability discovery, richer
  progress reporting) as real integrations demand it — extending an
  ABC and its one reference implementation is cheap; shrinking a rich
  speculative API would not be.
