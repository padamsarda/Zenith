"""ContextAssembler: composes the brief a provider session receives.

Context flows between long-running sessions through durable state, not
live memory: every session leaves a `summary` behind, and the next
session's instructions are assembled — deterministically, from the
store alone — out of the plan goal, the task description, what
completed prerequisite work reported, and what previous attempts at
this task failed with. Because the brief is derived rather than stored,
it is always current, survives restarts by construction, and is
identical no matter which provider receives it (ADR 0010).
"""

from __future__ import annotations

from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.store.store import Store

NO_SUMMARY = "(no summary recorded)"


class ContextAssembler:
    """Builds session instructions from the durable history of a task."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def briefing(self, task: Task, project: Project) -> str:
        """Return the full instruction brief for working on `task`.

        Sections, in order: the project, the plan goal (when the task
        belongs to a plan), the task itself, summaries of completed
        dependency work, and summaries of previous failed or abandoned
        attempts. Sections with nothing to say are omitted.
        """
        sections = [f"Project: {project.name} ({project.root_path})"]
        sections.extend(self._goal_section(task))
        sections.append(self._task_section(task))
        sections.extend(self._prerequisites_section(task))
        sections.extend(self._attempts_section(task))
        return "\n\n".join(sections)

    def _goal_section(self, task: Task) -> list[str]:
        """The plan goal this task serves, when it belongs to a plan."""
        if task.plan_id is None:
            return []
        plan = self._store.get_plan(task.plan_id)
        lines = [f"Goal: {plan.goal}"]
        if plan.description:
            lines.append(plan.description)
        return ["\n".join(lines)]

    def _task_section(self, task: Task) -> str:
        """The task title and description."""
        lines = [f"Task: {task.title}"]
        if task.description:
            lines.append(task.description)
        return "\n".join(lines)

    def _prerequisites_section(self, task: Task) -> list[str]:
        """What each DONE dependency's work reported, oldest task first."""
        dependencies = sorted(
            (self._store.get_task(dependency_id) for dependency_id in task.depends_on),
            key=lambda dependency: (dependency.created_at, str(dependency.task_id)),
        )
        lines = [
            f"- {dependency.title}: {self._outcome_summary(dependency)}"
            for dependency in dependencies
            if dependency.status is TaskStatus.DONE
        ]
        if not lines:
            return []
        return ["Completed prerequisite work:\n" + "\n".join(lines)]

    def _attempts_section(self, task: Task) -> list[str]:
        """What previous failed or abandoned attempts at this task left behind."""
        attempts = [
            session
            for session in self._store.list_sessions(task_id=task.task_id)
            if session.status in (SessionStatus.FAILED, SessionStatus.ABANDONED)
        ]
        if not attempts:
            return []
        lines = [
            f"- attempt {number} ({session.status.name}): {session.summary or NO_SUMMARY}"
            for number, session in enumerate(attempts, start=1)
        ]
        return ["Previous attempts at this task:\n" + "\n".join(lines)]

    def _outcome_summary(self, dependency: Task) -> str:
        """The summary of the session that completed `dependency`."""
        completed = [
            session
            for session in self._store.list_sessions(task_id=dependency.task_id)
            if session.status is SessionStatus.COMPLETED
        ]
        if not completed:
            return NO_SUMMARY
        return self._latest(completed).summary or NO_SUMMARY

    @staticmethod
    def _latest(sessions: list[Session]) -> Session:
        """The most recently started of `sessions` (they arrive oldest first)."""
        return sessions[-1]
