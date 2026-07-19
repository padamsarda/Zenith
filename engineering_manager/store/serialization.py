"""Conversion between domain objects and database rows.

Kept separate from `store.py` so the domain stays persistence-agnostic
and the SQL stays serialization-agnostic. Conventions: enums are stored
by `.name`, datetimes as ISO-8601 strings, UUIDs as their canonical
string form, and dependency sets as sorted JSON arrays (sorted so the
stored form is deterministic).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from shared.events.event import Event


@dataclass(frozen=True)
class EventLogEntry:
    """One row of the persistent event log.

    Events are stored as plain records, not reconstructed as their
    original `Event` subclasses — the log is for audit and history, and
    a record survives even if the event class it came from is later
    renamed or removed.
    """

    event_id: UUID
    name: str
    source: str
    timestamp: datetime
    payload: dict[str, Any]


def project_to_row(project: Project) -> dict[str, Any]:
    """Convert a Project to a database row dict."""
    return {
        "project_id": project.project_id,
        "name": project.name,
        "root_path": str(project.root_path),
        "description": project.description,
        "status": project.status.name,
        "created_at": project.created_at.isoformat(),
    }


def project_from_row(row: sqlite3.Row) -> Project:
    """Rebuild a Project from a database row."""
    return Project(
        project_id=row["project_id"],
        name=row["name"],
        root_path=Path(row["root_path"]),
        description=row["description"],
        status=ProjectStatus[row["status"]],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def task_to_row(task: Task) -> dict[str, Any]:
    """Convert a Task to a database row dict."""
    return {
        "task_id": str(task.task_id),
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "depends_on": json.dumps(sorted(str(dep) for dep in task.depends_on)),
        "status": task.status.name,
        "created_at": task.created_at.isoformat(),
    }


def task_from_row(row: sqlite3.Row) -> Task:
    """Rebuild a Task from a database row."""
    return Task(
        task_id=UUID(row["task_id"]),
        project_id=row["project_id"],
        title=row["title"],
        description=row["description"],
        priority=row["priority"],
        depends_on=frozenset(UUID(dep) for dep in json.loads(row["depends_on"])),
        status=TaskStatus[row["status"]],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def session_to_row(session: Session) -> dict[str, Any]:
    """Convert a Session to a database row dict."""
    return {
        "session_id": str(session.session_id),
        "task_id": str(session.task_id),
        "project_id": session.project_id,
        "provider_id": session.provider_id,
        "account_id": session.account_id,
        "model": session.model,
        "external_ref": session.external_ref,
        "summary": session.summary,
        "status": session.status.name,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    }


def session_from_row(row: sqlite3.Row) -> Session:
    """Rebuild a Session from a database row."""
    return Session(
        session_id=UUID(row["session_id"]),
        task_id=UUID(row["task_id"]),
        project_id=row["project_id"],
        provider_id=row["provider_id"],
        account_id=row["account_id"],
        model=row["model"],
        external_ref=row["external_ref"],
        summary=row["summary"],
        status=SessionStatus[row["status"]],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
    )


def account_to_row(account: ProviderAccount) -> dict[str, Any]:
    """Convert a ProviderAccount to a database row dict."""
    return {
        "provider_id": account.provider_id,
        "account_id": account.account_id,
        "label": account.label,
    }


def account_from_row(row: sqlite3.Row) -> ProviderAccount:
    """Rebuild a ProviderAccount from a database row."""
    return ProviderAccount(
        provider_id=row["provider_id"], account_id=row["account_id"], label=row["label"]
    )


def event_to_row(event: Event) -> dict[str, Any]:
    """Convert an Event to an event_log row dict.

    Payload values that are not JSON-serializable are stored via
    `str()` — the log must never be the reason an emit fails.
    """
    return {
        "event_id": str(event.event_id),
        "name": event.name,
        "source": event.source,
        "timestamp": event.timestamp.isoformat(),
        "payload": json.dumps(event.payload, default=str),
    }


def event_entry_from_row(row: sqlite3.Row) -> EventLogEntry:
    """Rebuild an EventLogEntry from an event_log row."""
    return EventLogEntry(
        event_id=UUID(row["event_id"]),
        name=row["name"],
        source=row["source"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        payload=json.loads(row["payload"]),
    )
