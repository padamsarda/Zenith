"""Store: the Engineering Manager's persistence API.

One class, explicit methods per entity — no ORM, no repositories-of-
repositories. `add_*` is strict (a duplicate ID raises), `update_*` is
strict (a missing ID raises), so calling code always states its intent
and silent overwrites cannot happen. Each method commits before
returning; multi-step operations that must stay consistent under
concurrent writers are a documented future concern (see
`docs/engineering_manager.md`), not a silent assumption.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import (
    AccountNotFoundError,
    DuplicateEntityError,
    ProjectNotFoundError,
    SessionNotFoundError,
    StoreError,
    TaskNotFoundError,
)
from engineering_manager.store.database import open_database
from engineering_manager.store.serialization import (
    EventLogEntry,
    account_from_row,
    account_to_row,
    event_entry_from_row,
    event_to_row,
    project_from_row,
    project_to_row,
    session_from_row,
    session_to_row,
    task_from_row,
    task_to_row,
)
from shared.events.event import Event


class Store:
    """SQLite-backed persistence for projects, tasks, sessions, accounts,
    and the event log.
    """

    def __init__(self, path: Path) -> None:
        """Open (creating and migrating if needed) the store at `path`."""
        self._connection = open_database(path)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()

    # -- projects ----------------------------------------------------------

    def add_project(self, project: Project) -> None:
        """Insert `project`.

        Raises:
            DuplicateEntityError: If the project ID already exists.
        """
        self._insert("projects", project_to_row(project), entity="project")

    def update_project(self, project: Project) -> None:
        """Rewrite the stored row for `project`.

        Raises:
            ProjectNotFoundError: If the project ID does not exist.
        """
        row = project_to_row(project)
        updated = self._update("projects", row, key={"project_id": row["project_id"]})
        if not updated:
            raise ProjectNotFoundError(f"Project '{project.project_id}' is not in the store.")

    def get_project(self, project_id: str) -> Project:
        """Return the project with `project_id`.

        Raises:
            ProjectNotFoundError: If the project ID does not exist.
        """
        row = self._connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(f"Project '{project_id}' is not in the store.")
        return project_from_row(row)

    def list_projects(self, status: ProjectStatus | None = None) -> list[Project]:
        """Return projects, optionally filtered by `status`, oldest first."""
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM projects ORDER BY created_at"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY created_at",
                (status.name,),
            ).fetchall()
        return [project_from_row(row) for row in rows]

    # -- tasks -------------------------------------------------------------

    def add_task(self, task: Task) -> None:
        """Insert `task`.

        Raises:
            DuplicateEntityError: If the task ID already exists.
            StoreError: If the task references a project not in the store.
        """
        self._insert("tasks", task_to_row(task), entity="task")

    def update_task(self, task: Task) -> None:
        """Rewrite the stored row for `task`.

        Raises:
            TaskNotFoundError: If the task ID does not exist.
        """
        row = task_to_row(task)
        updated = self._update("tasks", row, key={"task_id": row["task_id"]})
        if not updated:
            raise TaskNotFoundError(f"Task {task.task_id} is not in the store.")

    def get_task(self, task_id: UUID) -> Task:
        """Return the task with `task_id`.

        Raises:
            TaskNotFoundError: If the task ID does not exist.
        """
        row = self._connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (str(task_id),)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task {task_id} is not in the store.")
        return task_from_row(row)

    def list_tasks(
        self, project_id: str | None = None, status: TaskStatus | None = None
    ) -> list[Task]:
        """Return tasks, optionally filtered, oldest first."""
        clauses: list[str] = []
        parameters: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            parameters.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status.name)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM tasks{where} ORDER BY created_at", parameters
        ).fetchall()
        return [task_from_row(row) for row in rows]

    # -- sessions ----------------------------------------------------------

    def add_session(self, session: Session) -> None:
        """Insert `session`.

        Raises:
            DuplicateEntityError: If the session ID already exists.
            StoreError: If the session references a task or project not
                in the store.
        """
        self._insert("sessions", session_to_row(session), entity="session")

    def update_session(self, session: Session) -> None:
        """Rewrite the stored row for `session`.

        Raises:
            SessionNotFoundError: If the session ID does not exist.
        """
        row = session_to_row(session)
        updated = self._update("sessions", row, key={"session_id": row["session_id"]})
        if not updated:
            raise SessionNotFoundError(f"Session {session.session_id} is not in the store.")

    def get_session(self, session_id: UUID) -> Session:
        """Return the session with `session_id`.

        Raises:
            SessionNotFoundError: If the session ID does not exist.
        """
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (str(session_id),)
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session {session_id} is not in the store.")
        return session_from_row(row)

    def list_sessions(
        self,
        task_id: UUID | None = None,
        statuses: Iterable[SessionStatus] | None = None,
    ) -> list[Session]:
        """Return sessions, optionally filtered, oldest first.

        Args:
            task_id: Only sessions for this task.
            statuses: Only sessions in any of these statuses.
        """
        clauses: list[str] = []
        parameters: list[str] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            parameters.append(str(task_id))
        if statuses is not None:
            names = [status.name for status in statuses]
            placeholders = ", ".join("?" for _ in names)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(names)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM sessions{where} ORDER BY started_at", parameters
        ).fetchall()
        return [session_from_row(row) for row in rows]

    # -- accounts ----------------------------------------------------------

    def add_account(self, account: ProviderAccount) -> None:
        """Insert `account`.

        Raises:
            DuplicateEntityError: If the (provider_id, account_id) pair
                already exists.
        """
        self._insert("accounts", account_to_row(account), entity="account")

    def remove_account(self, provider_id: str, account_id: str) -> None:
        """Delete the account identified by (`provider_id`, `account_id`).

        Raises:
            AccountNotFoundError: If the pair does not exist.
        """
        cursor = self._connection.execute(
            "DELETE FROM accounts WHERE provider_id = ? AND account_id = ?",
            (provider_id, account_id),
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise AccountNotFoundError(
                f"Account '{account_id}' on provider '{provider_id}' is not in the store."
            )

    def get_account(self, provider_id: str, account_id: str) -> ProviderAccount:
        """Return the account identified by (`provider_id`, `account_id`).

        Raises:
            AccountNotFoundError: If the pair does not exist.
        """
        row = self._connection.execute(
            "SELECT * FROM accounts WHERE provider_id = ? AND account_id = ?",
            (provider_id, account_id),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError(
                f"Account '{account_id}' on provider '{provider_id}' is not in the store."
            )
        return account_from_row(row)

    def list_accounts(self, provider_id: str | None = None) -> list[ProviderAccount]:
        """Return accounts, optionally filtered by provider, in insertion order."""
        if provider_id is None:
            rows = self._connection.execute(
                "SELECT * FROM accounts ORDER BY rowid"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM accounts WHERE provider_id = ? ORDER BY rowid",
                (provider_id,),
            ).fetchall()
        return [account_from_row(row) for row in rows]

    # -- event log ---------------------------------------------------------

    def append_event(self, event: Event) -> None:
        """Append `event` to the persistent event log."""
        self._insert("event_log", event_to_row(event), entity="event")

    def list_events(self, limit: int | None = None) -> list[EventLogEntry]:
        """Return event log entries, newest first, up to `limit`."""
        query = "SELECT * FROM event_log ORDER BY timestamp DESC, rowid DESC"
        if limit is not None:
            rows = self._connection.execute(f"{query} LIMIT ?", (limit,)).fetchall()
        else:
            rows = self._connection.execute(query).fetchall()
        return [event_entry_from_row(row) for row in rows]

    # -- shared SQL helpers ------------------------------------------------

    def _insert(self, table: str, row: dict[str, object], *, entity: str) -> None:
        """INSERT `row` into `table`, translating constraint violations.

        Raises:
            DuplicateEntityError: On a primary-key collision.
            StoreError: On any other integrity failure (e.g. a foreign
                key referencing a row that does not exist).
        """
        columns = ", ".join(row)
        placeholders = ", ".join(f":{column}" for column in row)
        try:
            with self._connection:
                self._connection.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", row
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEntityError(
                    f"A {entity} with this ID is already in the store."
                ) from exc
            raise StoreError(f"Could not insert {entity}: {exc}") from exc

    def _update(self, table: str, row: dict[str, object], *, key: dict[str, object]) -> bool:
        """UPDATE `row` in `table` matched by `key`; return True if a row changed."""
        assignments = ", ".join(f"{column} = :{column}" for column in row if column not in key)
        conditions = " AND ".join(f"{column} = :{column}" for column in key)
        with self._connection:
            cursor = self._connection.execute(
                f"UPDATE {table} SET {assignments} WHERE {conditions}", row
            )
        return cursor.rowcount > 0
