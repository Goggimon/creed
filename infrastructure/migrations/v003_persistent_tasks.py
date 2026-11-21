from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """v3: Persistent task orchestration, step checkpoints, event timelines, and approvals."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step_index INTEGER NOT NULL DEFAULT 0,
            steps_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            retry_max_attempts INTEGER NOT NULL DEFAULT 1,
            retry_backoff_s REAL NOT NULL DEFAULT 0.05,
            timeout_s REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_checkpoints (
            task_id TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            name TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            result TEXT,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (task_id, step_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            step_index INTEGER,
            message TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_approvals (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            action TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_approvals_task_id ON task_approvals(task_id)")
