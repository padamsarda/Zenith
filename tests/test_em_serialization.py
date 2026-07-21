"""Tests for domain-object <-> database-row conversion."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import (
    PlanStatus,
    ProjectStatus,
    SessionStatus,
    TaskStatus,
)
from engineering_manager.domain.task import Task
from engineering_manager.events import TaskAdded
from engineering_manager.store.serialization import (
    account_from_row,
    account_to_row,
    event_entry_from_row,
    event_to_row,
    plan_from_row,
    plan_to_row,
    project_from_row,
    project_to_row,
    session_from_row,
    session_to_row,
    task_from_row,
    task_to_row,
)


def as_row(values: dict[str, Any]) -> sqlite3.Row:
    """Materialize a dict as a real sqlite3.Row, as the store would see it."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(f"CREATE TABLE row_test ({columns})")
    connection.execute(f"INSERT INTO row_test ({columns}) VALUES ({placeholders})", values)
    row = connection.execute("SELECT * FROM row_test").fetchone()
    connection.close()
    return row


def test_project_round_trip(tmp_path: Path) -> None:
    project = Project(
        project_id="zenith",
        name="Zenith",
        root_path=tmp_path,
        description="The assistant",
        status=ProjectStatus.PAUSED,
    )

    assert project_from_row(as_row(project_to_row(project))) == project


def test_plan_round_trip() -> None:
    plan = Plan(
        project_id="zenith",
        goal="Ship plugins",
        description="Everything for plugin support",
        status=PlanStatus.IN_PROGRESS,
    )

    assert plan_from_row(as_row(plan_to_row(plan))) == plan


def test_task_round_trip() -> None:
    task = Task(
        project_id="zenith",
        title="Write docs",
        description="All of them",
        priority=7,
        depends_on=frozenset({uuid4(), uuid4()}),
        plan_id=uuid4(),
        status=TaskStatus.READY,
    )

    assert task_from_row(as_row(task_to_row(task))) == task


def test_task_without_plan_round_trips_to_none() -> None:
    task = Task(project_id="zenith", title="Write docs")

    restored = task_from_row(as_row(task_to_row(task)))

    assert restored == task
    assert restored.plan_id is None


def test_task_depends_on_is_stored_as_sorted_json() -> None:
    dependencies = frozenset({uuid4(), uuid4(), uuid4()})
    task = Task(project_id="zenith", title="Write docs", depends_on=dependencies)

    stored = json.loads(task_to_row(task)["depends_on"])

    assert stored == sorted(str(dep) for dep in dependencies)


def test_session_round_trip() -> None:
    session = Session(
        task_id=uuid4(),
        project_id="zenith",
        provider_id="claude",
        account_id="personal",
        model="claude-sonnet-5",
        external_ref="conversation-42",
        summary="Done",
        status=SessionStatus.COMPLETED,
    )
    session.close()

    assert session_from_row(as_row(session_to_row(session))) == session


def test_session_round_trip_with_open_fields() -> None:
    session = Session(
        task_id=uuid4(), project_id="zenith", provider_id="claude", account_id="personal"
    )

    restored = session_from_row(as_row(session_to_row(session)))

    assert restored == session
    assert restored.ended_at is None
    assert restored.external_ref is None
    assert restored.resume_at is None
    assert restored.starting_revision is None
    assert restored.ending_revision is None


def test_session_revisions_round_trip() -> None:
    session = Session(
        task_id=uuid4(),
        project_id="zenith",
        provider_id="claude",
        account_id="personal",
        status=SessionStatus.COMPLETED,
    )
    session.stamp_starting_revision("abc123")
    session.close(summary="Done", ending_revision="def456")

    restored = session_from_row(as_row(session_to_row(session)))

    assert restored == session
    assert restored.starting_revision == "abc123"
    assert restored.ending_revision == "def456"


def test_session_resume_at_round_trips() -> None:
    session = Session(
        task_id=uuid4(),
        project_id="zenith",
        provider_id="claude",
        account_id="personal",
        resume_at=datetime(2026, 7, 20, 17, 0, 0, tzinfo=timezone.utc),
        status=SessionStatus.INTERRUPTED,
    )

    restored = session_from_row(as_row(session_to_row(session)))

    assert restored == session
    assert restored.resume_at == session.resume_at


def test_account_round_trip() -> None:
    account = ProviderAccount(provider_id="claude", account_id="personal", label="Personal")

    assert account_from_row(as_row(account_to_row(account))) == account


def test_event_round_trip_preserves_identity_and_payload() -> None:
    event = TaskAdded(
        source="engineering_manager", payload={"task_id": "abc", "title": "Write docs"}
    )

    entry = event_entry_from_row(as_row(event_to_row(event)))

    assert entry.event_id == event.event_id
    assert entry.name == "TaskAdded"
    assert entry.source == "engineering_manager"
    assert entry.timestamp == event.timestamp
    assert entry.payload == event.payload


def test_event_payload_with_non_json_values_is_stringified() -> None:
    task_id = uuid4()
    event = TaskAdded(source="engineering_manager", payload={"task_id": task_id})

    entry = event_entry_from_row(as_row(event_to_row(event)))

    assert entry.payload == {"task_id": str(task_id)}
