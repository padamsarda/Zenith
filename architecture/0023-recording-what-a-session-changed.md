# 0023 — Recording what a session changed, as an observation that cannot fail

- Status: Accepted
- Date: 2026-07-21

## Context

The engineering report lists DONE tasks with the prose summary the
session wrote about itself. That summary is the provider's claim, not a
record of what happened. ADR 0019 already established why a claim is not
evidence — it added verification precisely because "the provider says it
finished" is not the same as "it works" — but verification only produces
a pass or a fail. It answers *did this hold up*, never *what moved*.

So after an unattended run the first question a human asks — show me
what this actually changed — had no answer in durable state. ADR 0022
made that gap concrete rather than theoretical: a misconfigured
permission mode produced sessions that exited 0, reported no error, and
wrote a confident summary while changing nothing at all. Nothing in the
store could distinguish that from real work, because nothing in the
store described the repository.

## Decision

Add `RevisionProbe` (`orchestration/revisions.py`), a policy seam of the
same shape as `AssignmentPolicy`, `RetryPolicy`, `VerificationPolicy`,
and `StopCondition`. Two methods: `current_revision(project)` stamps
where a project stands, and `changes_between(project, start, end)`
reports a `RevisionDiff` of files changed, insertions, and deletions.
`NoRevisionProbe` records nothing and is the default, so behavior is
unchanged for anyone who does not opt in. `GitRevisionProbe` shells out
to `git rev-parse` and `git diff --numstat` through the standard
library.

Two properties are load-bearing.

**A probe never raises.** A missing `git`, a project that is not a
repository, a repository with no commits, a revision since garbage
collected — each is reported as `None`. This is stricter than the rule
ADR 0019 gives `verify`, and deliberately so. A failed verification is
*about* the work, so it becomes an ordinary recoverable task failure. A
probe is not about the work; it runs on paths that have already
succeeded, at dispatch and at close. A probe that raised would convert
completed work into a failed tick — it would destroy the very thing it
exists to observe.

**`None` and `RevisionDiff(0, 0, 0)` are different answers.** `None` is
an absent measurement; the zero diff is a measurement that found
nothing. Collapsing them would let "we could not look" render in a
report as "the session changed nothing", which is exactly the false
confidence this ADR exists to remove.

## Consequences

The report can show evidence instead of assertions, and the failure mode
ADR 0022 describes becomes visible in the ordinary output rather than
requiring someone to go read the repository.

What is measured is committed history, not the working tree. A session
that edits files without committing reads as a zero diff — honest, but
not what a naive reader expects, so callers must read an empty diff as
"nothing landed in history" rather than "nothing was done". Measuring
the working tree instead would have made the number depend on when the
probe happened to run, which is worse: a diff that changes depending on
observation timing is not evidence.

Stamping two revisions per session costs two `git` invocations on paths
that are already running a subprocess-backed provider session, so the
overhead is not material. A probe that wanted to measure something other
than git — a build artifact hash, a coverage delta — is a new subclass,
with no change to the dispatcher or the session-closing path.
