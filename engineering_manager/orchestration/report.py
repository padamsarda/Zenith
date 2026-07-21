"""Engineering reports: a human-readable status of one managed project.

Everything the execution engine does — dispatch, retry, verification,
interruption — is only visible today by reading the CLI's `status`/`log`
output or subscribing to the event bus. Neither answers "what happened
while I was away" in a form meant to be read start to finish. `build_report`
composes that view, deterministically, from durable state alone (the same
principle ADR 0010's `ContextAssembler` applies to session briefs);
`render_markdown` turns it into the text a human — or a future dashboard
— actually reads.

One thing the report cannot read out of the store: what a session
actually changed on disk. The store holds the two revisions the
dispatcher stamped around each session, but turning those into a diff
takes a `RevisionProbe` (ADR 0023), so `build_report` accepts one and
measures the finished work with it. Without a probe the report reads
exactly as it did before — the summary a session wrote about itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.orchestration.graph import Blockage, blockages
from engineering_manager.orchestration.revisions import (
    NoRevisionProbe,
    RevisionDiff,
    RevisionProbe,
)
from engineering_manager.store.serialization import EventLogEntry
from engineering_manager.store.store import Store
from shared.utils.time_utils import utc_now

ATTENTION_EVENT_NAME = "AttentionRequired"
DEFAULT_ATTENTION_LIMIT = 10
NO_SUMMARY = "(no summary recorded)"
NO_CHANGES = "Nothing landed in version control."
NO_REASON = "(no reason recorded)"


@dataclass(frozen=True)
class ProjectReport:
    """Everything durable state can say about one project, right now.

    `revisions_by_task` carries a diff only for tasks that could
    actually be measured: the session recorded both revisions and the
    probe read them. A task absent from it was never measured, which is
    a different fact from a task measured at zero, and the two are
    rendered differently (ADR 0023).
    """

    project: Project
    generated_at: datetime
    plans: tuple[Plan, ...]
    tasks_by_status: dict[TaskStatus, tuple[Task, ...]]
    sessions: tuple[Session, ...]
    blockages: tuple[Blockage, ...]
    attention: tuple[EventLogEntry, ...]
    revisions_by_task: dict[UUID, RevisionDiff]

    @property
    def tasks(self) -> tuple[Task, ...]:
        """Every task in the project, across every status."""
        return tuple(task for group in self.tasks_by_status.values() for task in group)


def build_report(
    store: Store,
    project_id: str,
    *,
    clock: Callable[[], datetime] = utc_now,
    attention_limit: int = DEFAULT_ATTENTION_LIMIT,
    revision_probe: RevisionProbe | None = None,
) -> ProjectReport:
    """Compose a `ProjectReport` for `project_id` from the store alone.

    `revision_probe` is the one input that reaches outside the store: it
    turns the revisions stamped around each session into a diff. It
    defaults to `NoRevisionProbe`, which measures nothing.

    Raises:
        ProjectNotFoundError: If `project_id` is not managed.
    """
    project = store.get_project(project_id)
    tasks = store.list_tasks(project_id=project_id)
    tasks_by_status = {
        status: tuple(task for task in tasks if task.status is status) for status in TaskStatus
    }
    sessions = tuple(
        sorted(
            (
                session
                for task in tasks
                for session in store.list_sessions(task_id=task.task_id)
            ),
            key=lambda session: session.started_at,
        )
    )
    return ProjectReport(
        project=project,
        generated_at=clock(),
        plans=tuple(store.list_plans(project_id=project_id)),
        tasks_by_status=tasks_by_status,
        sessions=sessions,
        blockages=tuple(blockages(tasks)),
        attention=_recent_attention(store, tasks, attention_limit),
        revisions_by_task=_measure_revisions(
            revision_probe or NoRevisionProbe(),
            project,
            tasks_by_status[TaskStatus.DONE],
            sessions,
        ),
    )


def _measure_revisions(
    probe: RevisionProbe,
    project: Project,
    tasks: tuple[Task, ...],
    sessions: tuple[Session, ...],
) -> dict[UUID, RevisionDiff]:
    """Measure what the session behind each finished task changed.

    Only finished tasks are measured. A probe may shell out to another
    process, so measuring work the report never shows a delta for would
    be paid-for silence.

    A task is left out of the result whenever the measurement could not
    be made: no completed session, a session missing either revision
    (nothing was stamped, so there is no span to diff), or a probe that
    reported `None`. Guessing a zero for any of those would state that
    nothing changed on the strength of never having looked.
    """
    sessions_by_task = _completed_sessions_by_task(sessions)
    measured: dict[UUID, RevisionDiff] = {}
    for task in tasks:
        session = sessions_by_task.get(task.task_id)
        if session is None:
            continue
        if session.starting_revision is None or session.ending_revision is None:
            continue
        diff = probe.changes_between(
            project, session.starting_revision, session.ending_revision
        )
        if diff is not None:
            measured[task.task_id] = diff
    return measured


def _recent_attention(
    store: Store, tasks: list[Task], limit: int
) -> tuple[EventLogEntry, ...]:
    """The most recent `AttentionRequired` log entries naming one of `tasks`."""
    task_ids = {str(task.task_id) for task in tasks}
    matches: list[EventLogEntry] = []
    for entry in store.list_events():
        if entry.name != ATTENTION_EVENT_NAME:
            continue
        if entry.payload.get("task_id") not in task_ids:
            continue
        matches.append(entry)
        if len(matches) >= limit:
            break
    return tuple(matches)


def render_markdown(report: ProjectReport) -> str:
    """Render `report` as a Markdown document a human can read top to bottom."""
    sections = [
        _header(report),
        _plans_section(report),
        _task_summary_section(report),
        _completed_work_section(report),
        _needs_review_section(report),
        _failed_work_section(report),
        _blocked_section(report),
        _attention_section(report),
        _sessions_section(report),
    ]
    return "\n\n".join(section for section in sections if section)


def _header(report: ProjectReport) -> str:
    project = report.project
    lines = [
        f"# Engineering Report: {project.name} ({project.project_id})",
        f"Generated: {report.generated_at.isoformat(timespec='seconds')}",
        f"Status: {project.status.name}",
    ]
    if project.description:
        lines.append(project.description)
    return "\n".join(lines)


def _plans_section(report: ProjectReport) -> str:
    if not report.plans:
        return "## Plans\nNo plans recorded."
    lines = ["## Plans"]
    for plan in report.plans:
        task_count = sum(1 for task in report.tasks if task.plan_id == plan.plan_id)
        lines.append(f"- [{plan.status.name}] {plan.goal} ({plan.plan_id}) — {task_count} task(s)")
    return "\n".join(lines)


def _task_summary_section(report: ProjectReport) -> str:
    lines = ["## Task Summary"]
    total = len(report.tasks)
    lines.append(f"Total: {total}")
    for status in TaskStatus:
        count = len(report.tasks_by_status[status])
        if count:
            lines.append(f"- {status.name}: {count}")
    return "\n".join(lines)


def _completed_work_section(report: ProjectReport) -> str:
    """What the project actually delivered, task by task.

    A status breakdown says three tasks are DONE; it does not say what
    was done. This is the part of the report a human reads to find out,
    and the reason the report is worth keeping after the run.

    The summary is what the session said about itself; the change line
    beneath it, when a probe measured one, is what the repository says.
    """
    finished = report.tasks_by_status[TaskStatus.DONE]
    if not finished:
        return ""
    sessions_by_task = _completed_sessions_by_task(report.sessions)
    attempts = _attempts_by_task(report)
    lines = [f"## Completed Work ({len(finished)})"]
    for task in finished:
        lines.append(f"- {task.title} ({task.task_id})")
        lines.append(f"  - {_summary_for(sessions_by_task, task.task_id)}")
        changes = _changes_for(report.revisions_by_task.get(task.task_id))
        if changes:
            lines.append(f"  - {changes}")
        tries = attempts.get(task.task_id, 0)
        if tries > 1:
            lines.append(f"  - Took {tries} attempts.")
    return "\n".join(lines)


def _changes_for(diff: RevisionDiff | None) -> str:
    """How the report states what landed, or "" when nothing was measured.

    An unmeasured task says nothing at all, because a line about an
    observation that was never made would be worse than no line. A task
    measured at zero says so out loud: a session that reported success
    and landed nothing is precisely what this is here to expose.
    """
    if diff is None:
        return ""
    if not diff.files_changed:
        return NO_CHANGES
    return f"Changed {diff.files_changed} file(s): +{diff.insertions}/-{diff.deletions}."


def _needs_review_section(report: ProjectReport) -> str:
    pending = report.tasks_by_status[TaskStatus.NEEDS_REVIEW]
    if not pending:
        return ""
    sessions_by_task = _completed_sessions_by_task(report.sessions)
    lines = [f"## Needs Review ({len(pending)})"]
    for task in pending:
        detail = _summary_for(sessions_by_task, task.task_id)
        lines.append(f"- {task.title} ({task.task_id}): {detail}")
    return "\n".join(lines)


def _failed_work_section(report: ProjectReport) -> str:
    """What failed, and what the last attempt said about why.

    The status breakdown says two tasks are FAILED and the attention
    section says they exhausted their retries; neither says what went
    wrong. Coming back to a run that stopped is precisely when a human
    needs the reason, and without it the report sends them to the logs
    — which, for an unattended run, is the thing the report exists to
    replace.
    """
    failed = report.tasks_by_status[TaskStatus.FAILED]
    if not failed:
        return ""
    sessions_by_task = _failed_sessions_by_task(report.sessions)
    attempts = _attempts_by_task(report)
    lines = [f"## Failed Work ({len(failed)})"]
    for task in failed:
        lines.append(f"- {task.title} ({task.task_id})")
        session = sessions_by_task.get(task.task_id)
        reason = session.summary if session and session.summary else NO_REASON
        lines.append(f"  - Last attempt: {reason}")
        tries = attempts.get(task.task_id, 0)
        if tries > 1:
            lines.append(f"  - Failed {tries} times.")
    return "\n".join(lines)


def _failed_sessions_by_task(sessions: tuple[Session, ...]) -> dict[UUID, Session]:
    """The last FAILED session for each task, by task id."""
    sessions_by_task: dict[UUID, Session] = {}
    for session in sessions:
        if session.status is SessionStatus.FAILED:
            sessions_by_task[session.task_id] = session
    return sessions_by_task


def _completed_sessions_by_task(sessions: tuple[Session, ...]) -> dict[UUID, Session]:
    """The last COMPLETED session for each task, by task id."""
    sessions_by_task: dict[UUID, Session] = {}
    for session in sessions:
        if session.status is SessionStatus.COMPLETED:
            sessions_by_task[session.task_id] = session
    return sessions_by_task


def _attempts_by_task(report: ProjectReport) -> dict[UUID, int]:
    """How many sessions each task needed — a task that fought back shows here."""
    attempts: dict[UUID, int] = {}
    for session in report.sessions:
        attempts[session.task_id] = attempts.get(session.task_id, 0) + 1
    return attempts


def _summary_for(sessions_by_task: dict[UUID, Session], task_id: UUID) -> str:
    """What the session that finished `task_id` reported, if anything."""
    session = sessions_by_task.get(task_id)
    return session.summary if session and session.summary else NO_SUMMARY


def _blocked_section(report: ProjectReport) -> str:
    if not report.blockages:
        return ""
    titles = {task.task_id: task.title for task in report.tasks}
    lines = [f"## Blocked ({len(report.blockages)})"]
    for blockage in report.blockages:
        title = titles.get(blockage.task_id, str(blockage.task_id))
        parts = []
        if blockage.unmet:
            parts.append(f"waiting on {', '.join(str(dep) for dep in blockage.unmet)}")
        if blockage.impossible:
            parts.append(
                f"doomed by cancelled {', '.join(str(dep) for dep in blockage.impossible)}"
            )
        lines.append(f"- {title} ({blockage.task_id}): {'; '.join(parts)}")
    return "\n".join(lines)


def _attention_section(report: ProjectReport) -> str:
    if not report.attention:
        return ""
    lines = [f"## Attention ({len(report.attention)})"]
    for entry in report.attention:
        kind = entry.payload.get("kind", "notice")
        detail = entry.payload.get("detail", "")
        timestamp = entry.timestamp.isoformat(timespec="seconds")
        lines.append(f"- [{timestamp}] {kind}: {detail}")
    return "\n".join(lines)


def _sessions_section(report: ProjectReport) -> str:
    lines = [f"## Sessions ({len(report.sessions)} total)"]
    for status in SessionStatus:
        count = sum(1 for session in report.sessions if session.status is status)
        if count:
            lines.append(f"- {status.name}: {count}")
    return "\n".join(lines)
