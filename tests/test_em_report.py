"""Tests for build_report and render_markdown."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.events import AttentionRequired
from engineering_manager.exceptions import ProjectNotFoundError
from engineering_manager.orchestration.report import build_report, render_markdown
from engineering_manager.store.store import Store

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "em.db")
    store.add_project(Project(project_id="zenith", name="Zenith", root_path=tmp_path))
    yield store
    store.close()


def test_build_report_raises_on_unknown_project(store: Store) -> None:
    with pytest.raises(ProjectNotFoundError):
        build_report(store, "nope")


def test_build_report_groups_tasks_by_status(store: Store) -> None:
    ready = Task(project_id="zenith", title="Ready work", status=TaskStatus.READY)
    review = Task(project_id="zenith", title="Review me", status=TaskStatus.NEEDS_REVIEW)
    store.add_task(ready)
    store.add_task(review)

    report = build_report(store, "zenith", clock=lambda: NOW)

    assert report.generated_at == NOW
    assert report.tasks_by_status[TaskStatus.READY] == (ready,)
    assert report.tasks_by_status[TaskStatus.NEEDS_REVIEW] == (review,)
    assert report.tasks_by_status[TaskStatus.DONE] == ()
    assert set(report.tasks) == {ready, review}


def test_build_report_collects_sessions_across_tasks(store: Store) -> None:
    task = Task(project_id="zenith", title="Work")
    store.add_task(task)
    session = Session(
        task_id=task.task_id, project_id="zenith", provider_id="p", account_id="a"
    )
    store.add_session(session)

    report = build_report(store, "zenith")

    assert report.sessions == (session,)


def test_build_report_reports_blockages(store: Store) -> None:
    dependency = Task(project_id="zenith", title="Dep", status=TaskStatus.READY)
    store.add_task(dependency)
    dependent = Task(
        project_id="zenith",
        title="Dependent",
        status=TaskStatus.READY,
        depends_on=frozenset({dependency.task_id}),
    )
    store.add_task(dependent)

    report = build_report(store, "zenith")

    assert len(report.blockages) == 1
    assert report.blockages[0].task_id == dependent.task_id


def test_build_report_collects_attention_for_this_projects_tasks_only(store: Store) -> None:
    store.add_project(Project(project_id="other", name="Other", root_path=Path(".")))
    task = Task(project_id="zenith", title="Work")
    other_task = Task(project_id="other", title="Other work")
    store.add_task(task)
    store.add_task(other_task)
    store.append_event(
        AttentionRequired(
            source="engineering_manager",
            payload={"kind": "task_retries_exhausted", "task_id": str(task.task_id), "detail": "x"},
        )
    )
    store.append_event(
        AttentionRequired(
            source="engineering_manager",
            payload={
                "kind": "task_retries_exhausted",
                "task_id": str(other_task.task_id),
                "detail": "y",
            },
        )
    )

    report = build_report(store, "zenith")

    assert len(report.attention) == 1
    assert report.attention[0].payload["task_id"] == str(task.task_id)


def test_build_report_attention_respects_limit(store: Store) -> None:
    task = Task(project_id="zenith", title="Work")
    store.add_task(task)
    for index in range(5):
        store.append_event(
            AttentionRequired(
                source="engineering_manager",
                payload={"kind": "notice", "task_id": str(task.task_id), "detail": str(index)},
            )
        )

    report = build_report(store, "zenith", attention_limit=2)

    assert len(report.attention) == 2


def test_render_markdown_includes_all_sections(store: Store) -> None:
    ready = Task(project_id="zenith", title="Ready work", status=TaskStatus.READY)
    review = Task(project_id="zenith", title="Review me", status=TaskStatus.NEEDS_REVIEW)
    store.add_task(ready)
    store.add_task(review)
    session = Session(
        task_id=review.task_id,
        project_id="zenith",
        provider_id="p",
        account_id="a",
        status=SessionStatus.COMPLETED,
        summary="All green.",
    )
    session.close("All green.")
    store.add_session(session)
    store.append_event(
        AttentionRequired(
            source="engineering_manager",
            payload={"kind": "task_retries_exhausted", "task_id": str(ready.task_id), "detail": "d"},
        )
    )

    report = build_report(store, "zenith")
    rendered = render_markdown(report)

    assert "# Engineering Report: Zenith (zenith)" in rendered
    assert "## Task Summary" in rendered
    assert "READY: 1" in rendered
    assert "NEEDS_REVIEW: 1" in rendered
    assert "## Needs Review (1)" in rendered
    assert "Review me" in rendered and "All green." in rendered
    assert "## Attention (1)" in rendered
    assert "## Sessions (1 total)" in rendered


def test_render_markdown_on_empty_project_has_no_optional_sections(store: Store) -> None:
    report = build_report(store, "zenith")

    rendered = render_markdown(report)

    assert "## Plans" in rendered
    assert "No plans recorded." in rendered
    assert "## Needs Review" not in rendered
    assert "## Blocked" not in rendered
    assert "## Attention" not in rendered
    assert "## Sessions (0 total)" in rendered


def test_render_markdown_plans_section_counts_tasks(store: Store) -> None:
    from engineering_manager.domain.plan import Plan

    plan = Plan(project_id="zenith", goal="Ship it")
    store.add_plan(plan)
    task = Task(project_id="zenith", title="Do it", plan_id=plan.plan_id)
    store.add_task(task)

    report = build_report(store, "zenith")
    rendered = render_markdown(report)

    assert f"[DRAFT] Ship it ({plan.plan_id}) — 1 task(s)" in rendered
