# 0021 — The workflow as a first-class lifecycle: stop conditions and gate two in the loop

- Status: Accepted
- Date: 2026-07-21

## Context

Every step of the engineering lifecycle already existed as a facade
method: `plan_from_goal` (ADR 0020), `approve_plan` (ADR 0006), `run`
(ADR 0008), verification (ADR 0019), `project_report`. What did not
exist was the lifecycle. Walking the quickstart in `README.md` exactly
as written showed the seams:

1. `plan from-goal --account personal` failed. Registering an account
   was an undocumented prerequisite, and skipping it did not produce an
   error — the engine simply idled, warning once per tick forever.
2. `run` never returned. `max_ticks` bounds *loop iterations*, not
   work, so a caller had to guess how many ticks a goal would take and
   could not distinguish a finished run from an exhausted one.
3. `run` printed nothing. The engine logged what each tick moved, but
   no handler was ever configured, so an unattended run showed a blank
   terminal for hours.
4. The plan could never complete. `approve_plan` was documented as "the
   bulk form of human approval gate one", but gate two had no bulk
   form — closing a plan meant `task accept <uuid>` once per task.
5. Nothing could be tried without a live Claude Code subscription.

Individually these read as polish. Together they meant the documented
workflow could not be completed by anyone, including its authors.

A sixth problem was structural and only surfaced when the lifecycle was
actually run end to end. Gate two is what turns `NEEDS_REVIEW` into
`DONE`, and a task's dependents are not eligible to dispatch until it
*is* `DONE`. So "execute to quiescence, then accept" stalls every plan
deeper than one wave: wave one finishes, and the engine spins on an
interval with nothing eligible while wave two waits behind a gate
nobody is at. The obvious fix — letting the engine accept its own work
— would delete the gate ADR 0006 exists to defend.

## Decision

Add the lifecycle as a composition of what already exists, not as a new
subsystem. Three parts.

**1. `StopCondition` (`orchestration/stop.py`).** A policy seam of the
same shape as `AssignmentPolicy`, `RetryPolicy`, and
`VerificationPolicy`: `should_stop(store) -> str | None`, returning a
human-readable reason or None. `RunForever` is the default, so
`run`'s historical behavior is unchanged when `until` is omitted.
`WhenQuiescent` stops once nothing can advance without a human;
`WhenPlanSettled` scopes that to one plan. `run` returns a `RunReport`
distinguishing the three ways a loop can end — settled, budget
exhausted, interrupted — because a caller that cannot tell them apart
cannot report honestly.

The condition reads the store and nothing else. It is deliberately not
shown the `TickReport`: whether work remains is a property of durable
state, not of what one tick happened to change. This keeps the module
free of any dependency on the engine that calls it, and follows the
discipline ADR 0010 applies to context assembly.

Defining "can advance" correctly is the whole substance of the module.
The engine moves a task by itself only while it is `IN_PROGRESS`, or
`READY` *and dispatchable*. The qualifier is not a detail: a `READY`
task whose dependency sits in `NEEDS_REVIEW` is waiting on a human,
not on the engine. Worse, the property is **transitive** — a `READY`
task two hops downstream of a parked one is equally parked, though its
own status says `READY`. A non-transitive check reads that task as
advancing and reproduces exactly the symptom this ADR set out to remove:
an unattended loop ticking forever against work that cannot start. It
is tested directly (`tests/test_em_stop.py`).

**2. `accept_plan` — gate two, in bulk.** The missing symmetry with
`approve_plan`. It accepts only tasks actually in `NEEDS_REVIEW`,
leaving running, failed, and unapproved work untouched, and completes
the plan when that settles it. The gate is not weakened: a human still
decides. Only the unit of decision changes, from a task to a
decomposition — which is the unit they approved in the first place.

**3. The `workflow` command (`cli_workflow.py`).** One invocation that
calls the same facade methods in the order the lifecycle already
implied, stopping at both human gates rather than around them. `--yes`
and `--accept` answer those prompts in advance for unattended use,
which is consent recorded up front, not the absence of a gate; a
non-interactive stdin declines rather than assuming agreement.

Its loop is where the sixth problem is resolved: **execute, accept,
execute again**, until acceptance stops unblocking anything. The gate
moves to where it releases work instead of after everything has
stopped. This is a change of *placement*, not of authority — the
decision remains the human's, made once per round or pre-authorized for
all of them. Crucially it stays in the CLI, where the human's consent
lives; the engine still cannot accept its own work, and `ExecutionEngine`
is unchanged in this respect.

Supporting changes: the CLI configures logging for the commands that
run the engine, so an unattended run narrates itself; `workflow`
registers its account if new; each run writes a timestamped Markdown
report beside the database, because a report rendered only to a
terminal is gone when the window closes. `InMemoryProvider` gains an
optional `finish_after_checks`, letting the whole lifecycle be driven
with no external process, credentials, or network — so the documented
workflow is something a new contributor can actually run, and so it is
testable end to end in pytest.

## Consequences

The lifecycle is now demonstrable in one command, and terminates on a
statement about the work rather than a guess about ticks. A plan can
reach `COMPLETED`. Interruption is not a special path: state is
durable, so `workflow --resume <plan-id>` re-enters wherever a run left
off — and because a fresh process holds a provider that has never heard
of the earlier session, resuming exercises ADR 0008's crash-recovery
path for real (the provider reports the session as lost, the session
fails, and the retry policy re-queues it).

`ExecutionEngine.run` no longer ticks unconditionally, which narrows
ADR 0008's "run is nothing but tick-on-an-interval". That ADR is not
superseded: its substance is that *orchestration decisions live in
`tick`*, and they still do. `run` gained one decision only — whether to
loop again — delegated to an injected policy that reads durable state,
and defaulting to the old behavior. Anything richer (stopping on a
budget, on wall-clock time, on a failure rate) is a new `StopCondition`
subclass, with no engine change.

`accept_plan` makes it possible to accept many tasks with one command
and, with `--accept`, many rounds with one decision. That is the point,
and it is also the risk: bulk consent is still consent, and a human who
pre-authorizes acceptance is trusting the `VerificationPolicy` (ADR
0019) to be the thing that actually checks the work. The two features
are complements — `--accept` without a `--verify-command` means nobody
checked anything, and the documentation says so.

The simulated provider is a convenience for demonstration and testing,
not a second architecture: it is one optional argument on the existing
reference implementation, and every orchestration test still scripts
outcomes explicitly rather than relying on it.
