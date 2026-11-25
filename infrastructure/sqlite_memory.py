from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime

from core.ports.memory import MemoryError, MigrationError
from infrastructure.migrations import SQLiteMigrator


class SQLiteMemoryRepository:
    """SQLite-backed MemoryRepository adapter; never leaks sqlite3 rows or exceptions."""

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
            except MigrationError:
                raise
            except sqlite3.Error as exc:
                raise MemoryError(f"Database initialization failed: {exc}") from exc

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

    def count_notes_and_reminders(self) -> tuple[int, int]:
        with self.lock:
            try:
                with self._connect() as conn:
                    n = int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
                    r = int(conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0])
                    return n, r
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed counting notes and reminders: {exc}") from exc

    def list_notes(self, query: str = "") -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    if query.strip():
                        q = f"%{query.strip()}%"
                        rows = conn.execute(
                            "SELECT id, tag, note, timestamp FROM notes WHERE tag LIKE ? OR note LIKE ? ORDER BY id DESC",
                            (q, q),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT id, tag, note, timestamp FROM notes ORDER BY id DESC"
                        ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing notes: {exc}") from exc

    def search_notes(self, terms: list[str], candidate_limit: int = 200) -> list[dict]:
        clean_terms = []
        for t in terms:
            s = str(t or "").strip()
            if s and s not in clean_terms:
                clean_terms.append(s)
            if len(clean_terms) >= 12:
                break
        if not clean_terms or candidate_limit <= 0:
            return []

        clauses = []
        params: list[object] = []
        for term in clean_terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pat = f"%{escaped}%"
            clauses.append("(tag LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')")
            params.extend((pat, pat))
        params.append(int(candidate_limit))

        sql = (
            "SELECT id, tag, note, timestamp FROM notes "
            f"WHERE ({' OR '.join(clauses)}) "
            "ORDER BY timestamp DESC, id DESC LIMIT ?"
        )
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed searching notes: {exc}") from exc

    def add_note(self, tag: str, note: str, timestamp: str | None = None) -> dict:
        clean_tag = tag.strip() or "general"
        clean_note = note.strip()
        ts = timestamp or datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO notes (tag, note, timestamp) VALUES (?, ?, ?)",
                        (clean_tag, clean_note, ts),
                    )
                    conn.commit()
                    return {"id": cur.lastrowid, "tag": clean_tag, "note": clean_note, "timestamp": ts}
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed adding note: {exc}") from exc

    def delete_note_by_id(self, note_id: int) -> bool:
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                    conn.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed deleting note: {exc}") from exc

    def add_reminder(self, time_iso: str, message: str) -> dict:
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO reminders (time, message) VALUES (?, ?)",
                        (time_iso, message),
                    )
                    conn.commit()
                    return {"id": cur.lastrowid, "time": time_iso, "message": message}
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed adding reminder: {exc}") from exc

    def list_reminders(self) -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT id, time, message FROM reminders ORDER BY time ASC"
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing reminders: {exc}") from exc

    def pop_due_reminders(self, now_iso: str) -> list[dict]:
        now = datetime.fromisoformat(now_iso)
        triggered: list[dict] = []
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute("SELECT id, time, message FROM reminders").fetchall()
                    for row in rows:
                        if now >= datetime.fromisoformat(row["time"]):
                            triggered.append(
                                {"id": row["id"], "time": row["time"], "message": row["message"]}
                            )
                            conn.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))
                    if triggered:
                        conn.commit()
                return triggered
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed checking reminders: {exc}") from exc

    def ensure_conversation(self, session_id: str, title: str = "New Conversation") -> None:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (session_id, title, now, now),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed ensuring conversation: {exc}") from exc

    def create_conversation(self, title: str = "New Conversation") -> dict:
        sid = f"chat-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        clean_title = title.strip() or "New Conversation"
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (sid, clean_title, now, now),
                    )
                    conn.commit()
                    return {
                        "id": sid,
                        "title": clean_title,
                        "created_at": now,
                        "updated_at": now,
                        "message_count": 0,
                    }
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed creating conversation: {exc}") from exc

    def list_conversations(self) -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT c.id, c.title, c.created_at, c.updated_at,
                               COUNT(m.id) AS message_count
                        FROM conversations c
                        LEFT JOIN messages m ON c.id = m.session_id
                        GROUP BY c.id
                        ORDER BY c.updated_at DESC
                        """
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing conversations: {exc}") from exc

    def delete_conversation(self, session_id: str) -> bool:
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                    if session_id == "default":
                        conn.commit()
                        return True
                    cur = conn.execute("DELETE FROM conversations WHERE id = ?", (session_id,))
                    conn.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed deleting conversation: {exc}") from exc

    def save_message(self, session_id: str, role: str, content: str) -> None:
        ts = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (session_id, "New Conversation", ts, ts),
                    )
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (session_id, role, content, ts),
                    )
                    if role == "user":
                        row = conn.execute(
                            "SELECT title FROM conversations WHERE id = ?", (session_id,)
                        ).fetchone()
                        if row and row["title"] in ("New Conversation", "Primary Session"):
                            snippet = content.strip().replace("\n", " ")[:38]
                            if len(content.strip()) > 38:
                                snippet += "…"
                            conn.execute(
                                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                                (snippet, ts, session_id),
                            )
                        else:
                            conn.execute(
                                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                                (ts, session_id),
                            )
                    else:
                        conn.execute(
                            "UPDATE conversations SET updated_at = ? WHERE id = ?",
                            (ts, session_id),
                        )
                    conn.commit()
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed saving message: {exc}") from exc

    def get_messages(self, session_id: str = "default", limit: int = 60) -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT role, content, timestamp FROM (
                            SELECT id, role, content, timestamp FROM messages
                            WHERE session_id = ?
                            ORDER BY id DESC LIMIT ?
                        ) sub ORDER BY id ASC
                        """,
                        (session_id, limit),
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed getting messages: {exc}") from exc

    def list_workflows(self) -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT id, name, description, steps_json, created_at FROM workflows ORDER BY id ASC"
                    ).fetchall()
                    out = []
                    for r in rows:
                        d = dict(r)
                        try:
                            d["steps"] = json.loads(d.pop("steps_json"))
                        except Exception:
                            d["steps"] = []
                        out.append(d)
                    return out
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing workflows: {exc}") from exc

    def get_workflow(self, workflow_id: int | None = None, name: str | None = None) -> dict | None:
        with self.lock:
            try:
                with self._connect() as conn:
                    if workflow_id is not None:
                        row = conn.execute(
                            "SELECT id, name, description, steps_json FROM workflows WHERE id = ?",
                            (workflow_id,),
                        ).fetchone()
                    elif name is not None:
                        row = conn.execute(
                            "SELECT id, name, description, steps_json FROM workflows WHERE LOWER(name) = LOWER(?)",
                            (name.strip(),),
                        ).fetchone()
                    else:
                        return None
                    if not row:
                        return None
                    d = dict(row)
                    d["steps"] = json.loads(d.pop("steps_json"))
                    return d
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed getting workflow: {exc}") from exc

    def create_workflow(self, name: str, description: str, steps: list[dict]) -> dict:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO workflows (name, description, steps_json, created_at) VALUES (?, ?, ?, ?)",
                        (name.strip(), description.strip(), json.dumps(steps), now),
                    )
                    conn.commit()
                    return {
                        "id": cur.lastrowid,
                        "name": name.strip(),
                        "description": description.strip(),
                        "steps": steps,
                        "created_at": now,
                    }
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed creating workflow: {exc}") from exc

    def delete_workflow(self, workflow_id: int) -> bool:
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
                    conn.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed deleting workflow: {exc}") from exc

    def seed_workflows_if_empty(self, defaults: list[tuple[str, str, list[dict]]]) -> None:
        with self.lock:
            try:
                with self._connect() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
                    if count == 0:
                        now = datetime.now().isoformat()
                        for name, desc, steps in defaults:
                            conn.execute(
                                "INSERT OR IGNORE INTO workflows (name, description, steps_json, created_at) VALUES (?, ?, ?, ?)",
                                (name, desc, json.dumps(steps), now),
                            )
                        conn.commit()
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed seeding workflows: {exc}") from exc

    def list_flashcards(self, subject: str = "") -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    if subject and subject.lower() != "all":
                        rows = conn.execute(
                            "SELECT id, subject, chapter, front, back, mastered, created_at FROM jee_flashcards WHERE LOWER(subject) = LOWER(?) ORDER BY id DESC",
                            (subject,),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT id, subject, chapter, front, back, mastered, created_at FROM jee_flashcards ORDER BY id DESC"
                        ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing flashcards: {exc}") from exc

    def add_flashcard(self, subject: str, chapter: str, front: str, back: str) -> dict:
        now = datetime.now().isoformat()
        subj = subject.strip() or "Physics"
        chap = chapter.strip() or "General"
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO jee_flashcards (subject, chapter, front, back, mastered, created_at) VALUES (?, ?, ?, ?, 0, ?)",
                        (subj, chap, front.strip(), back.strip(), now),
                    )
                    conn.commit()
                    return {
                        "id": cur.lastrowid,
                        "subject": subj,
                        "chapter": chap,
                        "front": front.strip(),
                        "back": back.strip(),
                        "mastered": 0,
                        "created_at": now,
                    }
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed adding flashcard: {exc}") from exc

    def toggle_flashcard_mastery(self, card_id: int) -> bool:
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "UPDATE jee_flashcards SET mastered = CASE WHEN mastered = 1 THEN 0 ELSE 1 END WHERE id = ?",
                        (card_id,),
                    )
                    conn.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed toggling flashcard mastery: {exc}") from exc

    def delete_flashcard(self, card_id: int) -> bool:
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute("DELETE FROM jee_flashcards WHERE id = ?", (card_id,))
                    conn.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed deleting flashcard: {exc}") from exc

    def seed_flashcards_if_empty(self, seeds: list[tuple[str, str, str, str, int]]) -> None:
        with self.lock:
            try:
                with self._connect() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM jee_flashcards").fetchone()[0]
                    if count == 0:
                        now = datetime.now().isoformat()
                        for subj, chap, front, back, mast in seeds:
                            conn.execute(
                                "INSERT INTO jee_flashcards (subject, chapter, front, back, mastered, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (subj, chap, front, back, mast, now),
                            )
                        conn.commit()
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed seeding flashcards: {exc}") from exc

    def save_jee_test(self, subject: str, difficulty: str, score: int, total: int) -> dict:
        now = datetime.now().isoformat()
        with self.lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO jee_tests (subject, difficulty, score, total, created_at) VALUES (?, ?, ?, ?, ?)",
                        (subject, difficulty, int(score), int(total), now),
                    )
                    conn.commit()
                    return {
                        "id": cur.lastrowid,
                        "subject": subject,
                        "difficulty": difficulty,
                        "score": int(score),
                        "total": int(total),
                        "created_at": now,
                    }
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed saving JEE test: {exc}") from exc

    def list_jee_tests(self, limit: int = 20) -> list[dict]:
        with self.lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT id, subject, difficulty, score, total, created_at FROM jee_tests ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise MemoryError(f"Failed listing JEE tests: {exc}") from exc
