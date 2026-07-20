"""Tests for the Plan domain object."""

from __future__ import annotations

import pytest

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.states import PlanStatus
from engineering_manager.exceptions import DomainValidationError


def test_plan_defaults_to_draft() -> None:
    plan = Plan(project_id="zenith", goal="Ship the loader")

    assert plan.status is PlanStatus.DRAFT
    assert plan.description is None


def test_plan_ids_are_unique() -> None:
    first = Plan(project_id="zenith", goal="A")
    second = Plan(project_id="zenith", goal="B")

    assert first.plan_id != second.plan_id


def test_transition_draft_to_in_progress() -> None:
    plan = Plan(project_id="zenith", goal="Ship the loader")

    plan.transition_to(PlanStatus.IN_PROGRESS)

    assert plan.status is PlanStatus.IN_PROGRESS


def test_transition_in_progress_to_completed() -> None:
    plan = Plan(project_id="zenith", goal="Ship", status=PlanStatus.IN_PROGRESS)

    plan.transition_to(PlanStatus.COMPLETED)

    assert plan.status is PlanStatus.COMPLETED


def test_any_non_terminal_status_can_cancel() -> None:
    draft = Plan(project_id="zenith", goal="A")
    in_progress = Plan(project_id="zenith", goal="B", status=PlanStatus.IN_PROGRESS)

    draft.transition_to(PlanStatus.CANCELLED)
    in_progress.transition_to(PlanStatus.CANCELLED)

    assert draft.status is PlanStatus.CANCELLED
    assert in_progress.status is PlanStatus.CANCELLED


def test_draft_cannot_complete_directly() -> None:
    plan = Plan(project_id="zenith", goal="Ship the loader")

    with pytest.raises(DomainValidationError):
        plan.transition_to(PlanStatus.COMPLETED)


def test_terminal_statuses_cannot_transition() -> None:
    completed = Plan(project_id="zenith", goal="A", status=PlanStatus.COMPLETED)
    cancelled = Plan(project_id="zenith", goal="B", status=PlanStatus.CANCELLED)

    with pytest.raises(DomainValidationError):
        completed.transition_to(PlanStatus.CANCELLED)
    with pytest.raises(DomainValidationError):
        cancelled.transition_to(PlanStatus.IN_PROGRESS)


def test_fields_other_than_status_are_frozen() -> None:
    plan = Plan(project_id="zenith", goal="Ship the loader")

    with pytest.raises(AttributeError):
        plan.goal = "Something else"  # type: ignore[misc]
