"""Engineering reports: a human-readable status of one managed project.

Everything the execution engine does — dispatch, retry, verification,
interruption — is only visible today by reading the CLI's `status`/`log`
output or subscribing to the event bus. Neither answers "what happened
while I was away" in a form meant to be read start to finish. `build_report`
composes that view, deterministically, from durable state alone (the same
principle ADR 0010's `ContextAssembler` applies to session briefs);
`render_markdown` turns it into the text a human — or a future dashboard
— actually reads.
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
from engineering_manager.store.serialization import EventLogEntry
from engineering_manager.store.store import Store
from shared.utils.time_utils import utc_now

ATTENTION_EVENT_NAME = "AttentionRequired"
DEFAULT_ATTENTION_LIMIT = 10
NO_SUMMARY = "(no summary recorded)"


@dataclass(frozen=True)
class ProjectReport:
    """Everything durable state can say about one project, right now."""

    project: Project
    generated_at: datetime
    plans: tuple[Plan, ...]
    tasks_by_status: dict[TaskStatus, tuple[Task, ...]]
    sessions: tuple[Session, ...]
    blockages: tuple[Blockage, ...]
    attention: tuple[EventLogEntry, ...]

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
) -> ProjectReport:
    """Compose a `ProjectReport` for `project_id` from the store alone.

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
    )


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
        _needs_review_section(report),
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


def _needs_review_section(report: ProjectReport) -> str:
    pending = report.tasks_by_status[TaskStatus.NEEDS_REVIEW]
    if not pending:
        return ""
    sessions_by_task: dict[UUID, Session] = {}
    for session in report.sessions:
        if session.status is SessionStatus.COMPLETED:
            sessions_by_task[session.task_id] = session
    lines = [f"## Needs Review ({len(pending)})"]
    for task in pending:
        summary = sessions_by_task.get(task.task_id)
        detail = (summary.summary if summary and summary.summary else NO_SUMMARY)
        lines.append(f"- {task.title} ({task.task_id}): {detail}")
    return "\n".join(lines)


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
