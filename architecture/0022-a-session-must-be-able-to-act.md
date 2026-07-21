# 0022 — A session must be able to act, and must fail loudly when it cannot

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0021 made the lifecycle runnable end to end, and demonstrated it
against `InMemoryProvider`. The first attempt to run the *same*
lifecycle against `ClaudeCodeProvider` — the only provider that performs
real engineering work — found that it could not perform any.

`ClaudeCodeProvider` launches `claude --print <instructions>
--output-format json` with `stdin=subprocess.DEVNULL` (ADR 0014). Claude
Code's default permission mode asks a human to approve each file edit.
A `--print` session with no stdin can never receive that approval, so
every `Write`, `Edit`, and `Bash` call is denied. The session then:

- exits **0**,
- reports `is_error: false`,
- and returns a fluent `result` describing what it *would* have done
  ("The write to `hello.txt` was blocked — approve it and I'll create
  the file"),
- listing the blocked calls in a `permission_denials` array that nothing
  read.

`interpret_exit` therefore reported `FINISHED`. The engine completed the
session, the task moved to `NEEDS_REVIEW`, and a human — or `--accept` —
accepted work that had never touched the repository.

The verification gate (ADR 0019) does not catch this, and cannot. A test
suite that passed before a no-op still passes after it. Verification
proves the repository is *healthy*; it never claimed to prove that
anything *happened*. So the two mechanisms that exist to stop bad work
from being trusted both pass a session that did nothing at all.

This is the worst failure mode the Engineering Manager can have. A
provider that fails is recoverable — the retry policy exists for it. A
provider that silently succeeds at nothing corrupts the record: the plan
completes, the report lists delivered work, and the goal is not done.

## Decision

Two changes, one on each side of the contract.

**1. A permission-blocked session is a failed session.**
`_parse_success` (`providers/claude_code_output.py`) now inspects
`permission_denials`. A non-empty list yields `FAILED`, with a detail
naming the blocked tools and the remedy. The denial list is a fact the
provider already reported about its own run; reading it is the provider
adapter honoring ADR 0005's rule that providers report facts and
orchestration decides what they mean.

The failure is an ordinary one. It flows into the existing retry loop,
appears in the engineering report, and — because `ContextAssembler` (ADR
0010) feeds failed attempts' summaries into the next brief — the remedy
text reaches whoever, or whatever, tries next.

**2. Authority to act is an explicit argument.**
`ClaudeCodeProvider` gains `permission_mode` (default `"default"`),
passed to every `start_session` and preserved across `resume_session`;
`SessionSpec.metadata["permission_mode"]` overrides it per session. The
CLI exposes `--permission-mode` on `run` and `workflow`.

The default deliberately stays the safe one. Granting an unattended
subprocess authority to edit a repository is a real delegation, of the
same kind ADR 0021 says `--accept` is, and it should be recorded by a
human up front rather than assumed by a library default. What changes is
not the safety of the default but its **honesty**: before, the safe
default silently produced fake successes; now it produces a failure that
says exactly which flag to pass.

`plan from-goal` keeps the default mode. A planning session (ADR 0020)
only reads and emits JSON, so it needs no write authority — and a
planner that started editing the repository would be a bug, not a
feature.

## Consequences

The lifecycle can now be driven against real work, which is what ADRs
0014, 0019, 0020, and 0021 were all building toward.

A session that is blocked will now fail its retry budget and land in
front of a human, three failed attempts later, rather than reporting
success. That is noisier, and it is the correct trade: the noise names
its own fix, and the alternative is a plan that reaches `COMPLETED` with
nothing built.

The verification gate's scope is now explicit rather than assumed:
`VerificationPolicy` answers "is the repository still healthy?", not
"did this session do anything?". The second question is answered at the
provider boundary, where the evidence lives. A future policy that
asserts a session produced a change (comparing revisions before and
after) would strengthen this further, but it belongs alongside
verification, not inside it.

Provider adapters generally should be read with this failure in mind.
The lesson is not about permissions specifically: it is that a provider
reporting `FINISHED` is making a claim about *work*, and an adapter that
maps "the process exited cleanly" onto that claim without checking what
the process reported about itself will eventually launder a no-op into a
completed task.
