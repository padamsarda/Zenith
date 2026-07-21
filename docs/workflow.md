# The Engineering Workflow

One objective, from a sentence to a finished, reviewed, reported change.
This is the path through the Engineering Manager; everything else in
`docs/engineering_manager.md` is the machinery underneath it.

Read this one first, and run it before reading further — the simulated
provider means you can complete the whole lifecycle in a few seconds
without a Claude Code subscription, a network connection, or an API key.

## Try it in one minute

```bash
pip install -e ".[dev]"

python -m engineering_manager --db /tmp/demo.db project add demo "Demo" --path .
python -m engineering_manager --db /tmp/demo.db \
    workflow demo "Add a health check endpoint" \
    --provider in-memory --interval 0 --yes --accept
```

That drives the entire lifecycle: a goal is decomposed into a dependent
task graph, the plan is approved, each wave executes, finished work is
accepted, and a Markdown engineering report is written next to the
database. `--provider in-memory` simulates the engineering sessions —
nothing runs outside the process — so what you are watching is the real
orchestration, with the work itself stubbed.

Drop `--yes --accept` to be asked at each human gate instead.

## The ten steps, and the commands behind them

| # | Step | Command |
|---|------|---------|
| 1 | Create a project | `project add <id> <name> --path <repo>` |
| 2 | State an objective | `workflow <project> "<goal>"` |
| 3 | Produce a plan | (automatic — AI decomposition, ADR 0020) |
| 4 | Review and approve | prompted, or `--yes` / `plan approve <id>` |
| 5 | Start execution | (automatic) |
| 6 | Manage execution | (automatic — dispatch, retry, verify, resume) |
| 7 | Resume after a stop | `workflow <project> --resume <plan-id>` |
| 8 | Track progress | printed each round; `status`, `plan show`, `log` |
| 9 | Produce artifacts | written to `--artifacts` (default: beside the DB) |
| 10 | Produce a report | written automatically; `project report <id>` anytime |

Add `--track-changes` to any of them to record the git revision before
and after each session, so the report shows what each finished task
actually changed instead of only what its session claimed (ADR 0023).

Steps 2–10 are one invocation. The rest of this document explains what
that invocation does, and how to run each piece by hand when you need to.

## A real run

```bash
python -m engineering_manager project add zenith "Zenith" --path .

python -m engineering_manager workflow zenith \
    "Add a --json flag to the status command" \
    --account personal \
    --permission-mode bypassPermissions \
    --verify-command "python -m pytest" \
    --interval 30
```

`--account personal` names the execution resource; it is registered on
first use, so there is no separate setup step. `--verify-command` is the
verification gate (ADR 0019): a claimed completion is only trusted if
that command passes in the project directory. A failure re-enters the
ordinary retry loop rather than reaching review as if it had succeeded.

### `--permission-mode` is not optional in practice

**Without it, nothing happens, three times per task.** A Claude Code
session runs as `claude --print` with no stdin, so it cannot answer a
permission prompt; in the default mode every edit and every command is
denied. The session still exits cleanly, and before ADR 0022 that was
recorded as a *successful completion of untouched work*. It now fails
with an explanation instead — which is honest, but still means the task
burns its whole retry budget accomplishing nothing.

The modes, and what they actually permit:

| Mode | Grants | Use for |
|---|---|---|
| `default` | nothing, unattended | never, unattended |
| `acceptEdits` | file edits only | tasks that only write files |
| `bypassPermissions` | edits **and commands** | real engineering work |

`acceptEdits` looks like the cautious middle choice and is a trap:
engineering means running the test suite, the linter, `git` — all of
which are commands, all of which it denies. A session told to "add a
field and extend its tests" will happily write the code and then fail
trying to run pytest.

So unattended engineering runs need `bypassPermissions`, which grants an
autonomous subprocess the authority to run arbitrary commands in the
project directory. Treat that as the real decision it is. The safe way
to spend it is to point the project at a disposable checkout first:

```bash
git worktree add --detach ../zenith-work HEAD
python -m engineering_manager project relocate zenith --path ../zenith-work
```

`project relocate` moves where sessions execute without disturbing the
project's plans, tasks, sessions, or event log, so the record of the run
survives even though the code it produced is somewhere throwaway.

**Run unattended with `--verify-command`, especially with `--accept`.**
`--accept` pre-authorizes human gate two for every round of the run.
That is a real delegation of judgment, and the verification command is
what earns it — without one, nothing checks the work before it is
accepted.

## What happens between the gates

Each round of the run is one call into the execution engine, which ticks
on `--interval` until the plan settles:

- eligible tasks dispatch to provider sessions, respecting dependencies
  and the assignment policy;
- active sessions are reconciled against what the provider actually
  reports — finished, failed, rate-limited, or awaiting input;
- a session that hits a provider limit is interrupted and resumed
  automatically when its limit resets;
- a failed task is re-queued if the retry policy allows, and reported
  for a human if it does not;
- a claimed completion is verified before it is trusted.

The run stops when the plan can no longer advance without you — not
after a fixed number of ticks. Then finished work is presented for
acceptance, and if accepting it unblocks the next wave, the engine runs
again. That alternation is why a dependency chain completes in one
invocation: a task's dependents are not eligible until it is `DONE`, and
only gate two makes it `DONE` (ADR 0021).

## Being interrupted

Press Ctrl+C at any point. Nothing is lost — every fact the engine acts
on lives in SQLite — and the command tells you how to continue:

```bash
python -m engineering_manager workflow zenith --resume <plan-id> --account personal
```

Resuming is not a special recovery mode. The next tick reconciles
persisted state against what providers report, exactly as an ordinary
tick does (ADR 0008). A session the provider no longer recognises is
treated as lost work: it fails, and the retry policy decides whether the
task runs again.

## Tracking a run

The engine narrates itself to stderr while it runs. Alongside that:

```bash
python -m engineering_manager status                    # projects, task counts, open sessions
python -m engineering_manager plan show <plan-id>       # the task graph, as execution waves
python -m engineering_manager plan show <plan-id> --detail  # ...including task descriptions
python -m engineering_manager task show <task-id>       # one task, with its session history
python -m engineering_manager log --limit 50            # the durable event log
python -m engineering_manager project report zenith
```

`project report` renders the same Markdown the workflow writes as an
artifact: plans, a task breakdown, completed work, work awaiting review,
**failed work and why it failed**, blocked tasks, recent attention
notices, and a session summary. The failure reasons are what make it
usable as the first thing you read after an unattended run — a run that
stopped on failures should not send you back to the logs to find out
what went wrong.

`plan show --detail` and `task show` exist for the gates. Approving a
plan is consent to what its tasks *say*, not to their titles, so the
descriptions a session will actually be given have to be readable before
you approve them.

## Driving it by hand

`workflow` composes facade calls in a fixed order. Every one is also a
command, for when you want to stop between them:

```bash
python -m engineering_manager account add claude-code personal
python -m engineering_manager plan from-goal zenith "<goal>" --account personal
python -m engineering_manager plan show <plan-id>
python -m engineering_manager plan approve <plan-id>        # gate one, in bulk
python -m engineering_manager run --until quiescent --verify-command "python -m pytest"
python -m engineering_manager plan accept <plan-id>         # gate two, in bulk
python -m engineering_manager project report zenith --out report.md
```

`run --until quiescent` is the same stop condition `workflow` uses,
scoped to everything rather than one plan; the default (`--until
forever`) ticks until interrupted, which is what a long-lived operator
process wants. Individual tasks still have `task approve`, `task
accept`, `task rework`, `task retry`, and `task cancel` when a plan-wide
decision is too coarse.

`run` takes `--provider in-memory` as well, so this sequence can be
rehearsed without spending a real account on it.

## The two human gates

Both come from ADR 0006 and neither has been removed:

- **Gate one — approve.** `DRAFT -> READY`. Nothing dispatches until a
  human approves the decomposition. An AI-produced plan is exactly as
  reviewable as a hand-written one; it lands in `DRAFT` either way.
- **Gate two — accept.** `NEEDS_REVIEW -> DONE`. Finished work is not
  done until a human says so, and dependents stay blocked until then.

`--yes` and `--accept` answer these in advance. They are consent
recorded up front, which is why a non-interactive run without them
declines and exits rather than assuming agreement.

## Further reading

- [`docs/engineering_manager.md`](engineering_manager.md) — the
  architecture underneath this workflow, and the programmatic API.
- [ADR 0021](../architecture/0021-the-workflow-as-a-first-class-lifecycle.md)
  — why the lifecycle is shaped this way, including the dependency
  deadlock that determined where gate two happens.
- [ADR 0006](../architecture/0006-task-lifecycle-and-human-approval-gates.md)
  — the task lifecycle and the two gates.
- [ADR 0019](../architecture/0019-verification-gate-before-needs-review.md)
  — the verification gate.
