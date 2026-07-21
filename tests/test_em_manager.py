"""Tests for the EngineeringManager facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.events import PlanDecomposed, TaskStatusChanged
from engineering_manager.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    OrchestrationError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from engineering_manager.manager import EngineeringManager
from engineering_manager.providers.base import ProviderSessionState, ProviderSessionStatus
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.store.store import Store
from shared.events.event import Event


@pytest.fixture
def manager(tmp_path: Path) -> EngineeringManager:
    manager = EngineeringManager(Store(tmp_path / "em.db"))
    manager.register_provider(InMemoryProvider())
    yield manager
    manager.close()


def test_add_project_persists_and_logs(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    assert manager.get_project("zenith").name == "Zenith"
    assert [entry.name for entry in manager.list_events()] == ["ProjectAdded"]


def test_add_project_with_invalid_id_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    with pytest.raises(DomainValidationError):
        manager.add_project("  ", "Zenith", tmp_path)


def test_add_duplicate_project_raises(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    with pytest.raises(DuplicateEntityError):
        manager.add_project("zenith", "Zenith", tmp_path)


def test_set_project_status_pauses_project(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    manager.set_project_status("zenith", ProjectStatus.PAUSED)

    assert manager.get_project("zenith").status is ProjectStatus.PAUSED


def test_add_task_requires_existing_project(manager: EngineeringManager) -> None:
    with pytest.raises(ProjectNotFoundError):
        manager.add_task("missing", "Write docs")


def test_add_task_with_missing_dependency_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from uuid import uuid4

    manager.add_project("zenith", "Zenith", tmp_path)

    with pytest.raises(TaskNotFoundError):
        manager.add_task("zenith", "Write docs", depends_on=[uuid4()])


def test_add_task_with_cross_project_dependency_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_project("other", "Other", tmp_path)
    foreign = manager.add_task("other", "Foreign work")

    with pytest.raises(DomainValidationError):
        manager.add_task("zenith", "Write docs", depends_on=[foreign.task_id])


def test_full_task_lifecycle_through_the_two_human_gates(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs", description="All of them")

    # Gate one: human approves the draft.
    manager.approve_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.READY

    # Autonomous stretch: dispatch and completion.
    session = manager.dispatch()
    assert session is not None
    assert manager.get_task(task.task_id).status is TaskStatus.IN_PROGRESS

    manager.complete_session(session.session_id, summary="Docs written.")
    assert manager.get_task(task.task_id).status is TaskStatus.NEEDS_REVIEW

    # Gate two: human accepts the work.
    manager.accept_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.DONE

    stored_session = manager.list_sessions(task_id=task.task_id)[0]
    assert stored_session.status is SessionStatus.COMPLETED
    assert stored_session.summary == "Docs written."


def test_draft_task_cannot_be_dispatched(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    manager.add_task("zenith", "Write docs")

    assert manager.dispatch() is None


def test_accept_task_before_review_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")

    with pytest.raises(DomainValidationError):
        manager.accept_task(task.task_id)


def test_rework_task_returns_it_to_ready(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.complete_session(session.session_id)

    manager.rework_task(task.task_id)

    assert manager.get_task(task.task_id).status is TaskStatus.READY


def test_retry_failed_task(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.fail_session(session.session_id, reason="crashed")
    assert manager.get_task(task.task_id).status is TaskStatus.FAILED

    manager.retry_task(task.task_id)

    assert manager.get_task(task.task_id).status is TaskStatus.READY


def test_revise_and_cancel_task(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)

    manager.revise_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.DRAFT

    manager.cancel_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.CANCELLED


def test_dependent_task_dispatches_only_after_dependency_done(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    dependency = manager.add_task("zenith", "Foundation")
    dependent = manager.add_task(
        "zenith", "Building", depends_on=[dependency.task_id], priority=10
    )
    manager.approve_task(dependency.task_id)
    manager.approve_task(dependent.task_id)

    # Despite lower priority, the dependency dispatches first.
    first = manager.dispatch()
    assert first.task_id == dependency.task_id

    manager.complete_session(first.session_id)
    manager.accept_task(dependency.task_id)

    second = manager.dispatch()
    assert second.task_id == dependent.task_id


def test_account_add_remove_and_events(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_account("in-memory", "personal", label="Personal")
    assert len(manager.list_accounts()) == 1

    manager.remove_account("in-memory", "personal")
    assert manager.list_accounts() == []

    names = [entry.name for entry in manager.list_events()]
    assert names == ["AccountRemoved", "AccountAdded"]


def test_facade_events_reach_bus_subscribers(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    received: list[Event] = []
    manager.events.subscribe(TaskStatusChanged, received.append)
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")

    manager.approve_task(task.task_id)

    assert len(received) == 1
    assert received[0].payload["to"] == "READY"


def test_event_log_tells_the_whole_story(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.complete_session(session.session_id)
    manager.accept_task(task.task_id)

    names = [entry.name for entry in manager.list_events()]
    assert names == [
        "TaskStatusChanged",  # NEEDS_REVIEW -> DONE
        "TaskStatusChanged",  # IN_PROGRESS -> NEEDS_REVIEW
        "SessionStatusChanged",  # ACTIVE -> COMPLETED
        "SessionStarted",
        "TaskStatusChanged",  # READY -> IN_PROGRESS
        "TaskStatusChanged",  # DRAFT -> READY
        "TaskAdded",
        "AccountAdded",
        "ProjectAdded",
    ]


def test_add_plan_and_list_plans(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    plan = manager.add_plan("zenith", "Ship plugins", description="All of it")

    assert manager.get_plan(plan.plan_id).goal == "Ship plugins"
    assert [p.plan_id for p in manager.list_plans(project_id="zenith")] == [plan.plan_id]


def test_add_task_into_plan_and_list_plan_tasks(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    plan = manager.add_plan("zenith", "Ship plugins")

    task = manager.add_task("zenith", "Write the loader", plan_id=plan.plan_id)

    assert [t.task_id for t in manager.plan_tasks(plan.plan_id)] == [task.task_id]


def test_add_task_into_foreign_project_plan_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_project("other", "Other", tmp_path)
    plan = manager.add_plan("other", "Elsewhere")

    with pytest.raises(DomainValidationError):
        manager.add_task("zenith", "Misfiled", plan_id=plan.plan_id)


def test_add_task_into_cancelled_plan_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    plan = manager.add_plan("zenith", "Ship plugins")
    manager.cancel_plan(plan.plan_id)

    with pytest.raises(DomainValidationError):
        manager.add_task("zenith", "Too late", plan_id=plan.plan_id)


def test_approve_plan_readies_tasks_for_dispatch(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    plan = manager.add_plan("zenith", "Ship plugins")
    task = manager.add_task("zenith", "Write the loader", plan_id=plan.plan_id)

    assert manager.eligible_tasks() == []

    manager.approve_plan(plan.plan_id)

    assert [t.task_id for t in manager.eligible_tasks()] == [task.task_id]


def test_accepting_last_task_completes_plan(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from engineering_manager.domain.states import PlanStatus

    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    plan = manager.add_plan("zenith", "Ship plugins")
    task = manager.add_task("zenith", "Write the loader", plan_id=plan.plan_id)
    manager.approve_plan(plan.plan_id)
    session = manager.dispatch()
    manager.complete_session(session.session_id, summary="done")

    manager.accept_task(task.task_id)

    assert manager.get_plan(plan.plan_id).status is PlanStatus.COMPLETED


def test_cancelling_last_open_task_completes_plan(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from engineering_manager.domain.states import PlanStatus

    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    plan = manager.add_plan("zenith", "Ship plugins")
    keep = manager.add_task("zenith", "Keep", plan_id=plan.plan_id)
    drop = manager.add_task("zenith", "Drop", plan_id=plan.plan_id)
    manager.approve_plan(plan.plan_id)
    session = manager.dispatch(keep.task_id)
    manager.complete_session(session.session_id)
    manager.accept_task(keep.task_id)

    manager.cancel_task(drop.task_id)

    assert manager.get_plan(plan.plan_id).status is PlanStatus.COMPLETED


def test_add_task_dependency_updates_graph(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    first = manager.add_task("zenith", "First")
    second = manager.add_task("zenith", "Second")

    manager.add_task_dependency(second.task_id, first.task_id)

    assert manager.get_task(second.task_id).depends_on == frozenset({first.task_id})
    assert [entry.name for entry in manager.list_events()][0] == "TaskDependencyAdded"


def test_add_task_dependency_rejects_cycles(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    first = manager.add_task("zenith", "First")
    second = manager.add_task("zenith", "Second", depends_on=[first.task_id])
    third = manager.add_task("zenith", "Third", depends_on=[second.task_id])

    with pytest.raises(DomainValidationError):
        manager.add_task_dependency(first.task_id, third.task_id)
    assert manager.get_task(first.task_id).depends_on == frozenset()


def test_add_task_dependency_rejects_cancelled_dependency(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    first = manager.add_task("zenith", "First")
    second = manager.add_task("zenith", "Second")
    manager.cancel_task(first.task_id)

    with pytest.raises(DomainValidationError):
        manager.add_task_dependency(second.task_id, first.task_id)


def test_add_task_dependency_rejects_cross_project_edge(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_project("other", "Other", tmp_path)
    ours = manager.add_task("zenith", "Ours")
    theirs = manager.add_task("other", "Theirs")

    with pytest.raises(DomainValidationError):
        manager.add_task_dependency(ours.task_id, theirs.task_id)


def test_blocked_tasks_reports_doomed_dependents(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    dependency = manager.add_task("zenith", "Dependency")
    dependent = manager.add_task("zenith", "Dependent", depends_on=[dependency.task_id])
    manager.cancel_task(dependency.task_id)

    (blockage,) = manager.blocked_tasks(project_id="zenith")

    assert blockage.task_id == dependent.task_id
    assert blockage.impossible == (dependency.task_id,)


def test_tick_drives_work_end_to_end(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write the loader")
    manager.approve_task(task.task_id)
    manager.add_account("in-memory", "personal")

    report = manager.tick()

    assert len(report.sessions_started) == 1
    assert manager.get_task(task.task_id).status is TaskStatus.IN_PROGRESS


def _script_planning_output(manager: EngineeringManager, detail: str) -> None:
    """Make the next planning session on the in-memory provider finish with `detail`."""
    provider = manager.providers.get("in-memory")
    original_start = provider.start_session

    def start_and_finish(spec: object) -> object:
        handle = original_start(spec)  # type: ignore[arg-type]
        provider.script_status(
            handle, ProviderSessionStatus(state=ProviderSessionState.FINISHED, detail=detail)
        )
        return handle

    provider.start_session = start_and_finish  # type: ignore[method-assign]


def test_plan_from_goal_creates_draft_tasks_with_dependencies(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from engineering_manager.domain.states import PlanStatus

    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "a")
    _script_planning_output(
        manager, '[{"title": "Design"}, {"title": "Build", "depends_on": [0]}]'
    )

    plan = manager.plan_from_goal("zenith", "Ship it", provider_id="in-memory", account_id="a")

    assert plan.status is PlanStatus.DRAFT
    tasks = {task.title: task for task in manager.plan_tasks(plan.plan_id)}
    assert set(tasks) == {"Design", "Build"}
    assert tasks["Build"].depends_on == frozenset({tasks["Design"].task_id})
    assert all(task.status is TaskStatus.DRAFT for task in tasks.values())


def test_plan_from_goal_publishes_plan_decomposed(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "a")
    _script_planning_output(manager, '[{"title": "Design"}]')
    received: list[Event] = []
    manager.events.subscribe(PlanDecomposed, received.append)

    plan = manager.plan_from_goal("zenith", "Ship it", provider_id="in-memory", account_id="a")

    assert len(received) == 1
    assert received[0].payload == {
        "plan_id": str(plan.plan_id),
        "project_id": "zenith",
        "task_count": 1,
    }


def test_plan_from_goal_skips_dependency_edges_that_would_cycle(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "a")
    _script_planning_output(
        manager,
        '[{"title": "A", "depends_on": [1]}, {"title": "B", "depends_on": [0]}]',
    )

    plan = manager.plan_from_goal("zenith", "Ship it", provider_id="in-memory", account_id="a")

    tasks = {task.title: task for task in manager.plan_tasks(plan.plan_id)}
    assert tasks["A"].depends_on == frozenset({tasks["B"].task_id})
    assert tasks["B"].depends_on == frozenset()  # would have cycled; skipped


def test_plan_from_goal_raises_and_leaves_an_empty_draft_plan_on_unparseable_output(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from engineering_manager.domain.states import PlanStatus

    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "a")
    _script_planning_output(manager, "I refuse to produce a plan.")

    with pytest.raises(OrchestrationError):
        manager.plan_from_goal("zenith", "Ship it", provider_id="in-memory", account_id="a")

    (plan,) = manager.list_plans(project_id="zenith")
    assert plan.status is PlanStatus.DRAFT
    assert manager.plan_tasks(plan.plan_id) == []


def test_plan_from_goal_raises_on_project_not_found(manager: EngineeringManager) -> None:
    with pytest.raises(ProjectNotFoundError):
        manager.plan_from_goal("nope", "Ship it", provider_id="in-memory", account_id="a")


def test_project_report_renders_markdown_from_live_state(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write the loader")
    manager.approve_task(task.task_id)

    report = manager.project_report("zenith")

    assert report.startswith("# Engineering Report: Zenith (zenith)")
    assert "READY: 1" in report


def test_project_report_raises_on_project_not_found(manager: EngineeringManager) -> None:
    with pytest.raises(ProjectNotFoundError):
        manager.project_report("nope")


def test_accept_plan_closes_every_reviewed_task_at_once(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from engineering_manager.domain.states import PlanStatus

    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    plan = manager.add_plan("zenith", "Ship plugins")
    first = manager.add_task("zenith", "Write the loader", plan_id=plan.plan_id)
    second = manager.add_task("zenith", "Document it", plan_id=plan.plan_id)
    manager.approve_plan(plan.plan_id)
    for _ in (first, second):
        session = manager.dispatch()
        manager.complete_session(session.session_id, summary="done")

    manager.accept_plan(plan.plan_id)

    assert manager.get_task(first.task_id).status is TaskStatus.DONE
    assert manager.get_task(second.task_id).status is TaskStatus.DONE
    assert manager.get_plan(plan.plan_id).status is PlanStatus.COMPLETED
