from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta

from core.ports.tasks import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalRequest,
    RetryPolicy,
    StepOutcome,
    TaskEvent,
    TaskLeaseLostError,
    TaskNotFoundError,
    TaskRecord,
    TaskStatus,
    TaskStep,
    TaskStorageError,
)
from infrastructure.migrations import SQLiteMigrator


def _serialize_steps(steps: list[TaskStep]) -> str:
    return json.dumps(
        [
            {
                "step_index": s.step_index,
                "name": s.name,
                "action": s.action,
                "args": s.args,
                "requires_approval": s.requires_approval,
                "idempotent": s.idempotent,
                "outcome": s.outcome.value,
                "result": s.result,
                "error": s.error,
                "attempts": s.attempts,
                "max_attempts": s.max_attempts,
                "updated_at": s.updated_at,
            }
            for s in steps
        ]
    )


def _deserialize_steps(raw: str) -> list[TaskStep]:
    data = json.loads(raw)
    return [
        TaskStep(
            step_index=int(item["step_index"]),
            name=item["name"],
            action=item["action"],
            args=item.get("args", {}),
            requires_approval=bool(item.get("requires_approval", False)),
            idempotent=bool(item.get("idempotent", False)),
            outcome=StepOutcome(item.get("outcome", StepOutcome.NOT_STARTED.value)),
            result=item.get("result"),
            error=item.get("error"),
            attempts=int(item.get("attempts", 0)),
            max_attempts=int(item.get("max_attempts", 1)),
            updated_at=item.get("updated_at", ""),
        )
        for item in data
    ]


def _row_to_approval(r: sqlite3.Row) -> ApprovalRequest:
    keys = r.keys()
    return ApprovalRequest(
        id=r["id"],
        task_id=r["task_id"],
        step_index=int(r["step_index"]),
        action=r["action"],
        args=json.loads(r["args_json"] or "{}"),
        reason=r["reason"],
        status=r["status"],
        created_at=r["created_at"],
        action_summary=r["action_summary"] if "action_summary" in keys else "",
        action_payload_hash=r["action_payload_hash"] if "action_payload_hash" in keys else "",
        expires_at=r["expires_at"] if "expires_at" in keys else None,
        resolved_at=r["resolved_at"],
        resolved_by=r["resolved_by"],
    )


class SQLiteTaskRepository:
    """SQLite-backed TaskRepository adapter with atomic lease claiming, checkpoints, & approvals."""

    def __init__(self, db_path: str, lock: threading.Lock, migrator: SQLiteMigrator | None = None):
        self.db_path = db_path
        self.lock = lock
        self.migrator = migrator or SQLiteMigrator(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.lock:
            try:
                self.migrator.migrate()
            except Exception as exc:
                raise TaskStorageError(f"Task storage initialization failed: {exc}") from exc

    def _row_to_task(self, row: sqlite3.Row, conn: sqlite3.Connection) -> TaskRecord:
        steps = _deserialize_steps(row["steps_json"])
        cp_rows = conn.execute(
            "SELECT step_index, outcome, attempts, result, error, updated_at FROM task_checkpoints WHERE task_id = ?",
            (row["id"],),
        ).fetchall()
        cp_map = {int(c["step_index"]): c for c in cp_rows}
        for s in steps:
            if s.step_index in cp_map:
                cp = cp_map[s.step_index]
                s.outcome = StepOutcome(cp["outcome"])
                s.attempts = int(cp["attempts"])
                s.result = cp["result"]
                s.error = cp["error"]
                s.updated_at = cp["updated_at"]

        keys = row.keys()
        return TaskRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            steps=steps,
            current_step_index=int(row["current_step_index"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            retry_policy=RetryPolicy(
                max_attempts=int(row["retry_max_attempts"]),
                backoff_s=float(row["retry_backoff_s"]),
            ),
            timeout_s=row["timeout_s"],
            owner_id=row["owner_id"] if "owner_id" in keys else None,
            lease_expires_at=row["lease_expires_at"] if "lease_expires_at" in keys else None,
        )

    def create_task(self, task: TaskRecord) -> TaskRecord:
        now = datetime.now().isoformat()
        task.created_at = task.created_at or now
        task.updated_at = task.updated_at or now
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO tasks (
                            id, conversation_id, title, status, current_step_index,
                            steps_json, metadata_json, retry_max_attempts, retry_backoff_s,
                            timeout_s, created_at, updated_at, started_at, completed_at, error,
                            owner_id, lease_expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task.id,
                            task.conversation_id,
                            task.title,
                            task.status.value,
                            task.current_step_index,
                            _serialize_steps(task.steps),
                            json.dumps(task.metadata),
                            task.retry_policy.max_attempts,
                            task.retry_policy.backoff_s,
                            task.timeout_s,
                            task.created_at,
                            task.updated_at,
                            task.started_at,
                            task.completed_at,
                            task.error,
                            task.owner_id,
                            task.lease_expires_at,
                        ),
                    )
                    for step in task.steps:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO task_checkpoints (
                                task_id, step_index, name, action, outcome, attempts, result, error, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                task.id,
                                step.step_index,
                                step.name,
                                step.action,
                                step.outcome.value,
                                step.attempts,
                                step.result,
                                step.error,
                                step.updated_at or now,
                            ),
                        )
                    conn.commit()
                    return task
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed creating task: {exc}") from exc

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self.lock:
            try:
                with self._connect() as conn:
                    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    if not row:
                        return None
                    return self._row_to_task(row, conn)
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed getting task: {exc}") from exc

    def list_tasks(
        self,
        conversation_id: str | None = None,
        statuses: list[TaskStatus] | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        with self.lock:
            try:
                with self._connect() as conn:
                    clauses = []
                    params: list = []
                    if conversation_id is not None:
                        clauses.append("conversation_id = ?")
                        params.append(conversation_id)
                    if statuses:
                        placeholders = ",".join("?" for _ in statuses)
                        clauses.append(f"status IN ({placeholders})")
                        params.extend(s.value for s in statuses)
                    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                    params.append(limit)
                    rows = conn.execute(
                        f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?",
                        params,
                    ).fetchall()
                    return [self._row_to_task(r, conn) for r in rows]
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed listing tasks: {exc}") from exc

    def update_task(self, task: TaskRecord) -> None:
        task.updated_at = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    if task.owner_id is not None:
                        existing = conn.execute(
                            "SELECT owner_id FROM tasks WHERE id = ?", (task.id,)
                        ).fetchone()
                        if not existing:
                            raise TaskNotFoundError(f"Task '{task.id}' not found")
                        if existing["owner_id"] is not None and existing["owner_id"] != task.owner_id:
                            raise TaskLeaseLostError(
                                f"Task '{task.id}' lease lost to '{existing['owner_id']}' (stale worker '{task.owner_id}')"
                            )
                    cur = conn.execute(
                        """
                        UPDATE tasks SET
                            status = ?,
                            current_step_index = ?,
                            steps_json = ?,
                            metadata_json = ?,
                            updated_at = ?,
                            started_at = ?,
                            completed_at = ?,
                            error = ?,
                            owner_id = ?,
                            lease_expires_at = ?
                        WHERE id = ?
                        """,
                        (
                            task.status.value,
                            task.current_step_index,
                            _serialize_steps(task.steps),
                            json.dumps(task.metadata),
                            task.updated_at,
                            task.started_at,
                            task.completed_at,
                            task.error,
                            task.owner_id,
                            task.lease_expires_at,
                            task.id,
                        ),
                    )
                    if cur.rowcount == 0:
                        raise TaskNotFoundError(f"Task '{task.id}' not found")
                    conn.commit()
            except (TaskNotFoundError, TaskLeaseLostError):
                raise
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed updating task: {exc}") from exc

    def claim_task(self, task_id: str, owner_id: str, lease_ttl_s: float = 30.0) -> bool:
        """Atomically claim a task lease so two instances/workers cannot run the same task."""
        now_dt = datetime.now()
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_ttl_s)).isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    cur = conn.execute(
                        """
                        UPDATE tasks
                        SET owner_id = ?, lease_expires_at = ?, updated_at = ?
                        WHERE id = ?
                          AND status IN ('queued', 'running')
                          AND (owner_id IS NULL OR owner_id = ? OR lease_expires_at IS NULL OR lease_expires_at <= ?)
                        """,
                        (owner_id, lease_until, now, task_id, owner_id, now),
                    )
                    conn.commit()
                    return cur.rowcount == 1
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed claiming task: {exc}") from exc

    def release_claim(self, task_id: str, owner_id: str) -> None:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        UPDATE tasks
                        SET owner_id = NULL, lease_expires_at = NULL, updated_at = ?
                        WHERE id = ? AND owner_id = ?
                        """,
                        (now, task_id, owner_id),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed releasing task claim: {exc}") from exc

    def save_checkpoint(self, task_id: str, step: TaskStep, current_step_index: int) -> None:
        now = datetime.now().isoformat()
        step.updated_at = now
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO task_checkpoints (
                            task_id, step_index, name, action, outcome, attempts, result, error, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            step.step_index,
                            step.name,
                            step.action,
                            step.outcome.value,
                            step.attempts,
                            step.result,
                            step.error,
                            now,
                        ),
                    )
                    conn.execute(
                        "UPDATE tasks SET current_step_index = ?, updated_at = ? WHERE id = ?",
                        (current_step_index, now, task_id),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed saving checkpoint: {exc}") from exc

    def append_event(self, event: TaskEvent) -> TaskEvent:
        ts = event.timestamp or datetime.now().isoformat()
        event.timestamp = ts
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO task_events (task_id, event_type, status, step_index, message, data_json, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.task_id,
                            event.event_type,
                            event.status,
                            event.step_index,
                            event.message,
                            json.dumps(event.data),
                            ts,
                        ),
                    )
                    conn.commit()
                    event.id = cur.lastrowid
                    return event
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed appending task event: {exc}") from exc

    def get_events(self, task_id: str) -> list[TaskEvent]:
        items, _ = self.get_events_page(task_id, offset=0, limit=10000)
        return items

    def get_events_page(self, task_id: str, offset: int = 0, limit: int = 50) -> tuple[list[TaskEvent], int]:
        with self.lock:
            try:
                with self._connect() as conn:
                    total = int(
                        conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id = ?", (task_id,)).fetchone()[0]
                    )
                    rows = conn.execute(
                        "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
                        (task_id, limit, offset),
                    ).fetchall()
                    items = [
                        TaskEvent(
                            id=int(r["id"]),
                            task_id=r["task_id"],
                            event_type=r["event_type"],
                            status=r["status"],
                            step_index=r["step_index"],
                            message=r["message"],
                            data=json.loads(r["data_json"] or "{}"),
                            timestamp=r["timestamp"],
                        )
                        for r in rows
                    ]
                    return items, total
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed reading task events: {exc}") from exc

    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO task_approvals (
                            id, task_id, step_index, action, args_json, reason, status,
                            created_at, action_summary, action_payload_hash, expires_at, resolved_at, resolved_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            approval.id,
                            approval.task_id,
                            approval.step_index,
                            approval.action,
                            json.dumps(approval.args),
                            approval.reason,
                            approval.status,
                            approval.created_at,
                            approval.action_summary,
                            approval.action_payload_hash,
                            approval.expires_at,
                            approval.resolved_at,
                            approval.resolved_by,
                        ),
                    )
                    conn.commit()
                    return approval
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed creating approval: {exc}") from exc

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self.lock:
            try:
                with self._connect() as conn:
                    row = conn.execute("SELECT * FROM task_approvals WHERE id = ?", (approval_id,)).fetchone()
                    if not row:
                        return None
                    return _row_to_approval(row)
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed getting approval: {exc}") from exc

    def list_pending_approvals(
        self,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[ApprovalRequest]:
        with self.lock:
            try:
                with self._connect() as conn:
                    clauses = ["a.status = 'pending'"]
                    params: list = []
                    if task_id is not None:
                        clauses.append("a.task_id = ?")
                        params.append(task_id)
                    if conversation_id is not None:
                        clauses.append("t.conversation_id = ?")
                        params.append(conversation_id)
                    sql = (
                        "SELECT a.* FROM task_approvals a "
                        "JOIN tasks t ON a.task_id = t.id "
                        f"WHERE {' AND '.join(clauses)} "
                        "ORDER BY a.created_at ASC"
                    )
                    rows = conn.execute(sql, params).fetchall()
                    return [_row_to_approval(r) for r in rows]
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed listing pending approvals: {exc}") from exc

    def resolve_approval(self, approval_id: str, status: str, resolved_by: str = "user") -> ApprovalRequest:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute(
                        "SELECT * FROM task_approvals WHERE id = ?", (approval_id,)
                    ).fetchone()
                    if not existing:
                        conn.execute("ROLLBACK")
                        raise TaskNotFoundError(f"Approval '{approval_id}' not found")
                    if existing["status"] != "pending":
                        conn.execute("ROLLBACK")
                        raise ApprovalConflictError(
                            f"Approval '{approval_id}' already resolved with status '{existing['status']}'"
                        )
                    exp = existing["expires_at"] if "expires_at" in existing.keys() else None
                    if exp and datetime.now() > datetime.fromisoformat(exp):
                        conn.execute(
                            "UPDATE task_approvals SET status = 'expired', resolved_at = ?, resolved_by = 'system' WHERE id = ? AND status = 'pending'",
                            (now, approval_id),
                        )
                        conn.commit()
                        raise ApprovalExpiredError(f"Approval '{approval_id}' expired at {exp}")

                    cur = conn.execute(
                        "UPDATE task_approvals SET status = ?, resolved_at = ?, resolved_by = ? WHERE id = ? AND status = 'pending'",
                        (status, now, resolved_by, approval_id),
                    )
                    if cur.rowcount == 0:
                        conn.execute("ROLLBACK")
                        raise ApprovalConflictError(f"Approval '{approval_id}' was already resolved concurrently")
                    conn.commit()
                    row = conn.execute("SELECT * FROM task_approvals WHERE id = ?", (approval_id,)).fetchone()
                    assert row is not None
                    return _row_to_approval(row)
            except (TaskNotFoundError, ApprovalConflictError, ApprovalExpiredError):
                raise
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed resolving approval: {exc}") from exc

    def invalidate_approval(self, approval_id: str, reason: str = "payload_changed") -> None:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE task_approvals SET status = 'invalidated', resolved_at = ?, resolved_by = ? WHERE id = ?",
                        (now, reason, approval_id),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise TaskStorageError(f"Failed invalidating approval: {exc}") from exc

    def close(self) -> None:
        with self.lock:
            try:
                conn = self._connect()
                try:
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                finally:
                    conn.close()
            except sqlite3.Error:
                pass
