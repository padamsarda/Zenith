"""Stop conditions: when an unattended `run` loop has done all it can.

`ExecutionEngine.run` ticks forever, which is right for a long-lived
operator process but wrong for the thing a human actually asks for —
"work on this until it's finished or you need me." Before this seam the
only bound was `max_ticks`, a count of loop iterations rather than a
statement about the work, so a caller had to guess how many ticks a goal
would take and could not tell a finished run from a merely exhausted one.

A `StopCondition` answers one question — is there any reason to tick
again? — from durable state alone, the same discipline `ContextAssembler`
(ADR 0010) and `build_report` follow. It deliberately does not see the
`TickReport`: whether work remains is a property of the store, not of
what one tick happened to change, and reading only the store keeps this
module free of any dependency on the engine that calls it.

The engine advances a task on its own only while that task is
IN_PROGRESS (a session is running or waiting to resume) or READY *and
dispatchable*. Every other status is parked on a human: DRAFT needs gate
one, NEEDS_REVIEW needs gate two, FAILED has already been offered to the
`RetryPolicy` and declined this tick, and DONE/CANCELLED are terminal.

The "and dispatchable" is not a detail. A READY task whose dependency
sits in NEEDS_REVIEW is not waiting on the engine — it is waiting on a
human, transitively — and treating it as advancing makes an unattended
run spin on an interval forever with nothing eligible to dispatch, which
is exactly the failure this seam exists to prevent. "quiescent"
therefore means "nothing is IN_PROGRESS, and every READY task is blocked
behind someone's decision" (ADR 0021).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.store.store import Store

# A dependency in one of these statuses is waiting on a human, so
# anything downstream of it is waiting on a human too.
PARKED_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.DRAFT,
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)

# Sessions in these statuses still have somewhere to go.
OPEN_SESSION_STATUSES: tuple[SessionStatus, ...] = (
    SessionStatus.ACTIVE,
    SessionStatus.INTERRUPTED,
)


class StopCondition(ABC):
    """Decides whether `ExecutionEngine.run` should tick again."""

    @abstractmethod
    def should_stop(self, store: Store) -> str | None:
        """Return why the loop should stop, or None to keep ticking.

        The return value is a human-readable reason so the caller can
        report *why* an unattended run ended — the difference between
        "finished" and "gave up" is the whole point of stopping.
        """


class RunForever(StopCondition):
    """Never stop; the historical behavior of `run`, and the default."""

    def should_stop(self, store: Store) -> str | None:
        """Return None, always."""
        return None


class WhenQuiescent(StopCondition):
    """Stop once nothing can advance without a human.

    Scoped to one project, or across every project when `project_id` is
    None. This is the condition behind an unattended run: the engine
    works until the queue is empty, everything left needs a decision,
    or the retry policy has given up — then hands back control instead
    of spinning on an interval forever.
    """

    def __init__(self, project_id: str | None = None) -> None:
        self._project_id = project_id

    def should_stop(self, store: Store) -> str | None:
        """Return a reason once no task is READY or IN_PROGRESS."""
        tasks = store.list_tasks(project_id=self._project_id)
        if _advancing(tasks, tasks) or _open_sessions(store, tasks):
            return None
        scope = f"project '{self._project_id}'" if self._project_id else "every project"
        return f"Nothing left to advance in {scope} without a human."


class WhenPlanSettled(StopCondition):
    """Stop once one plan is terminal, or can no longer advance alone.

    The condition an operator wants when they asked for a single goal:
    the run ends when that plan is COMPLETED or CANCELLED, or when what
    remains of it is waiting on review, approval, or a failure a human
    must look at. Work in other plans keeps running only insofar as the
    engine's own tick dispatches it — this condition simply stops
    watching once *this* goal has settled.
    """

    def __init__(self, plan_id: UUID) -> None:
        self._plan_id = plan_id

    def should_stop(self, store: Store) -> str | None:
        """Return a reason once the plan is terminal or parked on a human."""
        plan = store.get_plan(self._plan_id)
        tasks = store.list_tasks(plan_id=self._plan_id)
        universe = store.list_tasks(project_id=plan.project_id)
        if _advancing(tasks, universe) or _open_sessions(store, tasks):
            return None
        return f"Plan {self._plan_id} has settled ({plan.status.name})."


def _advancing(tasks: list[Task], universe: list[Task]) -> bool:
    """True if any of `tasks` is one the engine can still move by itself.

    `universe` supplies the statuses of dependencies, which may live
    outside `tasks` (another plan in the same project); a dependency
    missing from it is treated as parked, since the engine cannot show
    that it will ever complete.
    """
    by_id = {task.task_id: task for task in universe}
    return any(_is_live(task, by_id, set()) for task in tasks)


def _is_live(task: Task, by_id: dict[UUID, Task], visiting: set[UUID]) -> bool:
    """True if the engine can move `task` without a human deciding first.

    Liveness is transitive, and that is the whole subtlety: a READY task
    two hops downstream of something in NEEDS_REVIEW is just as parked
    as the task it waits on, even though its own status says READY. A
    non-transitive check reads that task as advancing and keeps an
    unattended run ticking forever against work that cannot start.

    `visiting` guards against a dependency cycle. The graph is acyclic
    by construction (`would_create_cycle` refuses the edge at write
    time), so this only ensures a corrupted store cannot hang the loop
    — a task that would have to clear itself never clears.
    """
    if task.status is TaskStatus.IN_PROGRESS:
        return True
    if task.status is not TaskStatus.READY or task.task_id in visiting:
        return False
    visiting.add(task.task_id)
    try:
        return all(
            _dependency_clears(by_id.get(dependency), by_id, visiting)
            for dependency in task.depends_on
        )
    finally:
        visiting.discard(task.task_id)


def _dependency_clears(
    dependency: Task | None, by_id: dict[UUID, Task], visiting: set[UUID]
) -> bool:
    """True if `dependency` is already satisfied, or will clear on its own."""
    if dependency is None:
        return False
    if dependency.status is TaskStatus.DONE:
        return True
    if dependency.status in PARKED_TASK_STATUSES:
        return False
    return _is_live(dependency, by_id, visiting)


def _open_sessions(store: Store, tasks: list[Task]) -> bool:
    """True if any of `tasks` still has a session that has somewhere to go.

    The dispatcher keeps a task and its session in lockstep, so this is
    normally implied by `_advancing`. It is checked anyway because
    stopping early on a session that is still live would abandon real
    work — the one mistake this condition must never make.
    """
    task_ids = {task.task_id for task in tasks}
    return any(
        session.task_id in task_ids
        for session in store.list_sessions(statuses=OPEN_SESSION_STATUSES)
    )
