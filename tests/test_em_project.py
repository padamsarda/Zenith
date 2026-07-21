"""Tests for the Project domain entity."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.states import ProjectStatus
from engineering_manager.exceptions import DomainValidationError


def make_project(tmp_path: Path) -> Project:
    return Project(project_id="zenith", name="Zenith", root_path=tmp_path)


def test_project_defaults_to_active(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    assert project.status is ProjectStatus.ACTIVE
    assert project.description is None
    assert project.created_at.tzinfo is not None


def test_project_fields_are_frozen(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        project.name = "Other"  # type: ignore[misc]


def test_project_status_cannot_be_assigned_directly(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        project.status = ProjectStatus.PAUSED  # type: ignore[misc]


def test_project_transition_to_valid_status(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    project.transition_to(ProjectStatus.PAUSED)
    assert project.status is ProjectStatus.PAUSED

    project.transition_to(ProjectStatus.ACTIVE)
    assert project.status is ProjectStatus.ACTIVE


def test_project_invalid_transition_raises_and_preserves_status(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.transition_to(ProjectStatus.ARCHIVED)

    with pytest.raises(DomainValidationError):
        project.transition_to(ProjectStatus.ACTIVE)
    assert project.status is ProjectStatus.ARCHIVED


def test_relocate_changes_the_root_path() -> None:
    project = Project(project_id="zenith", name="Zenith", root_path=Path("/old"))

    project.relocate(Path("/new"))

    assert project.root_path == Path("/new")


def test_relocate_rejects_a_non_path() -> None:
    project = Project(project_id="zenith", name="Zenith", root_path=Path("/old"))

    with pytest.raises(DomainValidationError):
        project.relocate("/new")  # type: ignore[arg-type]


def test_relocate_leaves_every_other_field_alone() -> None:
    project = Project(
        project_id="zenith", name="Zenith", root_path=Path("/old"), description="Two apps."
    )
    created_at = project.created_at

    project.relocate(Path("/new"))

    assert project.project_id == "zenith"
    assert project.name == "Zenith"
    assert project.description == "Two apps."
    assert project.created_at == created_at
    assert project.status is ProjectStatus.ACTIVE
