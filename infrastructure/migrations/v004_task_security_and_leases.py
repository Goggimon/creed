from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """v4: Add task worker lease columns and approval payload hash/expiry security fields."""
    task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "owner_id" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN owner_id TEXT")
    if "lease_expires_at" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN lease_expires_at TEXT")

    apr_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_approvals)").fetchall()}
    if "action_summary" not in apr_cols:
        conn.execute("ALTER TABLE task_approvals ADD COLUMN action_summary TEXT NOT NULL DEFAULT ''")
    if "action_payload_hash" not in apr_cols:
        conn.execute("ALTER TABLE task_approvals ADD COLUMN action_payload_hash TEXT NOT NULL DEFAULT ''")
    if "expires_at" not in apr_cols:
        conn.execute("ALTER TABLE task_approvals ADD COLUMN expires_at TEXT")
