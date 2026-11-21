from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """v2: Add non-destructive indexes for memory, messages, reminders, and flashcards."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jee_flashcards_subject ON jee_flashcards(subject)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_tag ON notes(tag)")
