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
from engineering_manager.orchestration.revisions import RevisionDiff, RevisionProbe
from engineering_manager.store.store import Store

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)


class RecordingRevisionProbe(RevisionProbe):
    """Reports one scripted diff, and remembers every span it was asked about.

    `current_revision` raises: stamping belongs to the dispatcher, and
    the report has no business doing it. Any test that trips this
    assertion has caught the report writing to the lifecycle it is
    supposed to only observe.
    """

    def __init__(self, diff: RevisionDiff | None) -> None:
        self._diff = diff
        self.spans: list[tuple[str, str, str]] = []

    def current_revision(self, project: Project) -> str | None:
        raise AssertionError("build_report must not stamp revisions.")

    def changes_between(
        self, project: Project, start_revision: str, end_revision: str
    ) -> RevisionDiff | None:
        self.spans.append((project.project_id, start_revision, end_revision))
        return self._diff


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


def _completed_task(
    store: Store,
    title: str,
    summary: str | None,
    *,
    starting_revision: str | None = None,
    ending_revision: str | None = None,
) -> Task:
    """A DONE task with one COMPLETED session reporting `summary`."""
    task = Task(project_id="zenith", title=title, status=TaskStatus.DONE)
    store.add_task(task)
    store.add_session(
        Session(
            task_id=task.task_id,
            project_id="zenith",
            provider_id="p",
            account_id="a",
            status=SessionStatus.COMPLETED,
            summary=summary,
            starting_revision=starting_revision,
            ending_revision=ending_revision,
        )
    )
    return task


def test_report_lists_what_was_delivered(store: Store) -> None:
    _completed_task(store, "Write the loader", "Added loader.py and tests.")

    markdown = render_markdown(build_report(store, "zenith", clock=lambda: NOW))

    assert "## Completed Work (1)" in markdown
    assert "Write the loader" in markdown
    assert "Added loader.py and tests." in markdown


def test_report_omits_completed_work_when_nothing_is_done(store: Store) -> None:
    store.add_task(Task(project_id="zenith", title="Pending", status=TaskStatus.READY))

    markdown = render_markdown(build_report(store, "zenith", clock=lambda: NOW))

    assert "Completed Work" not in markdown


def test_report_notes_a_task_that_needed_several_attempts(store: Store) -> None:
    task = _completed_task(store, "Stubborn work", "Finally done.")
    for _ in range(2):
        store.add_session(
            Session(
                task_id=task.task_id,
                project_id="zenith",
                provider_id="p",
                account_id="a",
                status=SessionStatus.FAILED,
            )
        )

    markdown = render_markdown(build_report(store, "zenith", clock=lambda: NOW))

    assert "Took 3 attempts." in markdown


def test_report_does_not_note_attempts_for_first_time_success(store: Store) -> None:
    _completed_task(store, "Easy work", "Done.")

    markdown = render_markdown(build_report(store, "zenith", clock=lambda: NOW))

    assert "attempts" not in markdown


def test_report_handles_completed_work_with_no_summary(store: Store) -> None:
    _completed_task(store, "Silent work", None)

    markdown = render_markdown(build_report(store, "zenith", clock=lambda: NOW))

    assert "Silent work" in markdown
    assert "(no summary recorded)" in markdown


def test_report_shows_what_a_completed_task_changed(store: Store) -> None:
    task = _completed_task(
        store,
        "Write the loader",
        "Added loader.py and tests.",
        starting_revision="rev-1",
        ending_revision="rev-2",
    )
    probe = RecordingRevisionProbe(RevisionDiff(files_changed=3, insertions=42, deletions=7))

    report = build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)
    markdown = render_markdown(report)

    assert report.revisions_by_task[task.task_id] == RevisionDiff(3, 42, 7)
    assert "Changed 3 file(s): +42/-7." in markdown
    # The measurement accompanies the prose rather than replacing it:
    # one is what the repository says, the other what the session said.
    assert "Added loader.py and tests." in markdown


def test_report_measures_between_the_revisions_the_session_recorded(store: Store) -> None:
    _completed_task(
        store, "Work", "Done.", starting_revision="rev-1", ending_revision="rev-9"
    )
    probe = RecordingRevisionProbe(RevisionDiff(1, 1, 0))

    build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)

    assert probe.spans == [("zenith", "rev-1", "rev-9")]


def test_report_states_plainly_when_a_completed_session_landed_nothing(
    store: Store,
) -> None:
    """A measured zero is the finding, not an absence of one."""
    task = _completed_task(
        store,
        "Confident work",
        "Implemented the whole thing.",
        starting_revision="rev-1",
        ending_revision="rev-1",
    )
    probe = RecordingRevisionProbe(RevisionDiff(0, 0, 0))

    report = build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)
    markdown = render_markdown(report)

    assert report.revisions_by_task[task.task_id] == RevisionDiff(0, 0, 0)
    assert "Nothing landed in version control." in markdown


def test_report_says_nothing_about_changes_when_the_probe_cannot_measure(
    store: Store,
) -> None:
    """An unmeasured task must not be rendered as a measured zero."""
    task = _completed_task(
        store, "Work", "Done.", starting_revision="rev-1", ending_revision="rev-2"
    )
    probe = RecordingRevisionProbe(None)

    report = build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)
    markdown = render_markdown(report)

    assert task.task_id not in report.revisions_by_task
    assert "Nothing landed in version control." not in markdown
    assert "Changed" not in markdown
    assert "Done." in markdown


@pytest.mark.parametrize(
    ("starting_revision", "ending_revision"),
    [(None, "rev-2"), ("rev-1", None), (None, None)],
)
def test_report_does_not_measure_a_session_missing_a_revision(
    store: Store, starting_revision: str | None, ending_revision: str | None
) -> None:
    """With no span to diff, the probe is never asked in the first place."""
    task = _completed_task(
        store,
        "Work",
        "Done.",
        starting_revision=starting_revision,
        ending_revision=ending_revision,
    )
    probe = RecordingRevisionProbe(RevisionDiff(3, 42, 7))

    report = build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)
    markdown = render_markdown(report)

    assert probe.spans == []
    assert task.task_id not in report.revisions_by_task
    assert "Changed" not in markdown
    assert "Work" in markdown


def test_report_without_a_probe_reads_as_it_did_before(store: Store) -> None:
    _completed_task(
        store, "Work", "Done.", starting_revision="rev-1", ending_revision="rev-2"
    )

    report = build_report(store, "zenith", clock=lambda: NOW)
    markdown = render_markdown(report)

    assert report.revisions_by_task == {}
    assert "Changed" not in markdown
    assert "Nothing landed in version control." not in markdown


def test_report_measures_only_finished_tasks(store: Store) -> None:
    """Awaiting-review work shows no delta, so nothing is spent measuring it."""
    task = Task(project_id="zenith", title="Review me", status=TaskStatus.NEEDS_REVIEW)
    store.add_task(task)
    store.add_session(
        Session(
            task_id=task.task_id,
            project_id="zenith",
            provider_id="p",
            account_id="a",
            status=SessionStatus.COMPLETED,
            summary="Ready for review.",
            starting_revision="rev-1",
            ending_revision="rev-2",
        )
    )
    probe = RecordingRevisionProbe(RevisionDiff(3, 42, 7))

    report = build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)

    assert probe.spans == []
    assert report.revisions_by_task == {}


def test_report_measures_the_session_that_finished_the_task(store: Store) -> None:
    """A task that failed twice is measured across its successful session."""
    task = _completed_task(
        store, "Stubborn work", "Finally done.", starting_revision="rev-3", ending_revision="rev-4"
    )
    store.add_session(
        Session(
            task_id=task.task_id,
            project_id="zenith",
            provider_id="p",
            account_id="a",
            status=SessionStatus.FAILED,
            starting_revision="rev-1",
            ending_revision="rev-2",
        )
    )
    probe = RecordingRevisionProbe(RevisionDiff(2, 5, 1))

    markdown = render_markdown(
        build_report(store, "zenith", clock=lambda: NOW, revision_probe=probe)
    )

    assert probe.spans == [("zenith", "rev-3", "rev-4")]
    assert "Changed 2 file(s): +5/-1." in markdown
    assert "Took 2 attempts." in markdown


def _failed_session(task: Task, reason: str) -> Session:
    """A closed FAILED session for `task`, carrying `reason` as its summary."""
    session = Session(
        task_id=task.task_id, project_id="zenith", provider_id="p", account_id="a"
    )
    session.transition_to(SessionStatus.FAILED)
    session.close(summary=reason)
    return session


def test_render_lists_failed_work_with_its_reason(store: Store) -> None:
    """A run that stopped on failures must say why, not just that it did."""
    task = Task(project_id="zenith", title="Add revision fields", status=TaskStatus.FAILED)
    store.add_task(task)
    store.add_session(_failed_session(task, "Denied permission to use: Bash."))

    markdown = render_markdown(build_report(store, "zenith"))

    assert "## Failed Work (1)" in markdown
    assert "Add revision fields" in markdown
    assert "Denied permission to use: Bash." in markdown


def test_render_omits_failed_work_when_nothing_failed(store: Store) -> None:
    store.add_task(Task(project_id="zenith", title="Fine", status=TaskStatus.DONE))

    markdown = render_markdown(build_report(store, "zenith"))

    assert "## Failed Work" not in markdown


def test_render_counts_repeated_failures_and_shows_the_latest_reason(store: Store) -> None:
    task = Task(project_id="zenith", title="Flaky work", status=TaskStatus.FAILED)
    store.add_task(task)
    store.add_session(_failed_session(task, "first reason"))
    store.add_session(_failed_session(task, "final reason"))

    markdown = render_markdown(build_report(store, "zenith"))

    assert "Failed 2 times." in markdown
    assert "final reason" in markdown


def test_render_reports_a_failed_task_with_no_recorded_reason(store: Store) -> None:
    task = Task(project_id="zenith", title="Silent failure", status=TaskStatus.FAILED)
    store.add_task(task)

    markdown = render_markdown(build_report(store, "zenith"))

    assert "## Failed Work (1)" in markdown
    assert "(no reason recorded)" in markdown
