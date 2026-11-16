import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from config.settings import config

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "about",
    "and", "or", "but", "not", "this", "that", "it", "i", "me", "my", "you",
    "what", "where", "when", "who", "how", "why", "do", "does", "did", "can",
}


class Module:
    name = "memory"
    intents = ["remember", "recall", "delete", "remind"]

    def __init__(self, lock):
        self.lock = lock
        self.db_path = config.db_file
        self.legacy_json = config.data_file
        self._init_db()
        self._migrate_legacy_json()
        self._seed_default_workflows()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tag TEXT NOT NULL,
                        note TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        time TEXT NOT NULL,
                        message TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflows (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        description TEXT NOT NULL,
                        steps_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jee_flashcards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        subject TEXT NOT NULL,
                        chapter TEXT NOT NULL,
                        front TEXT NOT NULL,
                        back TEXT NOT NULL,
                        mastered INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jee_tests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        subject TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        total INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    ("default", "Primary Session", now, now),
                )
                fc_count = conn.execute("SELECT COUNT(*) FROM jee_flashcards").fetchone()[0]
                if fc_count == 0:
                    seeds = [
                        ("Physics", "Modern Physics", "Stopping potential V0 in Photoelectric Effect", "eV0 = hf - phi0 = hc/lambda - phi0 (independent of intensity!)", 0),
                        ("Physics", "Current Electricity", "Wheatstone Bridge balance condition", "R1 / R2 = R3 / R4 -> zero current through galvanometer.", 0),
                        ("Physics", "Thermodynamics", "Adiabatic process equation & work done", "PV^gamma = const; W = (P1V1 - P2V2) / (gamma - 1) = nR(T1 - T2) / (gamma - 1).", 0),
                        ("Chemistry", "Chemical Bonding", "Paramagnetic diatomic molecules in MOT", "B2 (10e) and O2 (16e) have 2 unpaired electrons in pi* / pi orbitals.", 0),
                        ("Chemistry", "Electrochemistry", "Nernst Equation at 298 K", "E = E0 - (0.0591 / n) * log10(Q).", 0),
                        ("Maths", "Definite Integration", "King's Property", "Integral from a to b of f(x) dx = Integral from a to b of f(a + b - x) dx.", 0),
                        ("Maths", "Vectors & 3D", "Shortest distance between skew lines", "d = |(a2 - a1) . (b1 x b2)| / |b1 x b2|.", 0),
                    ]
                    for subj, chap, front, back, mast in seeds:
                        conn.execute(
                            "INSERT INTO jee_flashcards (subject, chapter, front, back, mastered, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (subj, chap, front, back, mast, now),
                        )
                conn.commit()

    def _migrate_legacy_json(self):
        if not os.path.exists(self.legacy_json):
            return
        with self.lock:
            try:
                with self._connect() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
                    rem_count = conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
                    if count > 0 or rem_count > 0:
                        return
                    with open(self.legacy_json, "r", encoding="utf-8") as f:
                        legacy = json.load(f)
                    for n in legacy.get("notes", []):
                        conn.execute(
                            "INSERT INTO notes (tag, note, timestamp) VALUES (?, ?, ?)",
                            (
                                n.get("tag", "general"),
                                n.get("note", ""),
                                n.get("timestamp", datetime.now().isoformat()),
                            ),
                        )
                    for r in legacy.get("reminders", []):
                        conn.execute(
                            "INSERT INTO reminders (time, message) VALUES (?, ?)",
                            (r.get("time", ""), r.get("message", "")),
                        )
                    conn.commit()
            except Exception:
                pass

    def _seed_default_workflows(self):
        defaults = [
            (
                "Study Mode",
                "Check Mac battery/uptime and open Visual Studio Code.",
                [
                    {"tool": "mac_system_info", "args": {}},
                    {"tool": "mac_open_app", "args": {"app_name": "Visual Studio Code"}},
                ],
            ),
            (
                "System Health Check",
                "Inspect Mac battery/uptime and paired Bluetooth devices.",
                [
                    {"tool": "mac_system_info", "args": {}},
                    {"tool": "bt_list_devices", "args": {}},
                ],
            ),
            (
                "Phone Sync",
                "Check Android ADB status and launch scrcpy screen mirror.",
                [
                    {"tool": "phone_connect", "args": {}},
                    {"tool": "phone_status", "args": {}},
                ],
            ),
        ]
        with self.lock:
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

    # -------- NOTES & REMINDERS --------
    def list_notes(self, query: str = "") -> list[dict]:
        with self.lock:
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

    def list_reminders(self) -> list[dict]:
        with self.lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, time, message FROM reminders ORDER BY time ASC"
                ).fetchall()
                return [dict(r) for r in rows]

    def add_note(self, tag: str, note: str) -> dict:
        ts = datetime.now().isoformat()
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO notes (tag, note, timestamp) VALUES (?, ?, ?)",
                    (tag.strip() or "general", note.strip(), ts),
                )
                conn.commit()
                return {"id": cur.lastrowid, "tag": tag, "note": note, "timestamp": ts}

    def delete_note_by_id(self, note_id: int) -> bool:
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                conn.commit()
                return cur.rowcount > 0

    # -------- CONVERSATIONS & MESSAGES --------
    def ensure_conversation(self, session_id: str, title: str = "New Conversation"):
        now = datetime.now().isoformat()
        with self.lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, title, now, now),
                )
                conn.commit()

    def create_conversation(self, title: str = "New Conversation") -> dict:
        sid = f"chat-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        with self.lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (sid, title.strip() or "New Conversation", now, now),
                )
                conn.commit()
                return {"id": sid, "title": title, "created_at": now, "updated_at": now, "message_count": 0}

    def list_conversations(self) -> list[dict]:
        with self.lock:
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

    def delete_conversation(self, session_id: str) -> bool:
        if session_id == "default":
            with self.lock:
                with self._connect() as conn:
                    conn.execute("DELETE FROM messages WHERE session_id = 'default'")
                    conn.commit()
            return True
        with self.lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                cur = conn.execute("DELETE FROM conversations WHERE id = ?", (session_id,))
                conn.commit()
                return cur.rowcount > 0

    def save_message(self, session_id: str, role: str, content: str):
        ts = datetime.now().isoformat()
        with self.lock:
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

    def get_messages(self, session_id: str = "default", limit: int = 60) -> list[dict]:
        with self.lock:
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

    # -------- WORKFLOWS --------
    def list_workflows(self) -> list[dict]:
        with self.lock:
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

    def get_workflow(self, workflow_id: int = None, name: str = None) -> dict | None:
        with self.lock:
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

    def create_workflow(self, name: str, description: str, steps: list[dict]) -> dict:
        now = datetime.now().isoformat()
        with self.lock:
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

    def delete_workflow(self, workflow_id: int) -> bool:
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
                conn.commit()
                return cur.rowcount > 0

    # -------- JEE FLASHCARDS & TESTS --------
    def list_flashcards(self, subject: str = "") -> list[dict]:
        with self.lock:
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

    def add_flashcard(self, subject: str, chapter: str, front: str, back: str) -> dict:
        now = datetime.now().isoformat()
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO jee_flashcards (subject, chapter, front, back, mastered, created_at) VALUES (?, ?, ?, ?, 0, ?)",
                    (subject.strip() or "Physics", chapter.strip() or "General", front.strip(), back.strip(), now),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid,
                    "subject": subject.strip() or "Physics",
                    "chapter": chapter.strip() or "General",
                    "front": front.strip(),
                    "back": back.strip(),
                    "mastered": 0,
                    "created_at": now,
                }

    def toggle_flashcard_mastery(self, card_id: int) -> bool:
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE jee_flashcards SET mastered = CASE WHEN mastered = 1 THEN 0 ELSE 1 END WHERE id = ?",
                    (card_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def delete_flashcard(self, card_id: int) -> bool:
        with self.lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM jee_flashcards WHERE id = ?", (card_id,))
                conn.commit()
                return cur.rowcount > 0

    def save_jee_test(self, subject: str, difficulty: str, score: int, total: int) -> dict:
        now = datetime.now().isoformat()
        with self.lock:
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

    def list_jee_tests(self, limit: int = 20) -> list[dict]:
        with self.lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, subject, difficulty, score, total, created_at FROM jee_tests ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

    # -------- INTENT HANDLERS --------
    def handle(self, intent, text, context):
        if intent == "remember":
            lower_text = text.lower()
            index = lower_text.find("remember")
            content = text[index + len("remember") :].strip()

            if not content:
                return "What would you like me to remember?"

            if ":" in content:
                tag, note = content.split(":", 1)
                tag = tag.strip()
                note = note.strip()
            else:
                tag = "general"
                note = content.strip()

            self.add_note(tag, note)
            context["last_topic"] = tag
            return f"Noted under '{tag}'."

        if intent == "recall":
            notes = list(reversed(self.list_notes()))
            if not notes:
                return "No saved notes."

            return "\n".join(
                f"{i + 1}. [{n['tag']}] {n['note']}" for i, n in enumerate(notes)
            )

        if intent == "delete":
            notes = list(reversed(self.list_notes()))
            match = re.search(r"\b(\d+)\b", text)
            if match:
                index = int(match.group(1)) - 1
                if 0 <= index < len(notes):
                    target = notes[index]
                    self.delete_note_by_id(target["id"])
                    return f"Deleted: {target['note']}"
                return "Note number out of range."

            query = text.lower().split("delete", 1)[1].strip()
            if query:
                for n in notes:
                    if query in n["tag"].lower() or query in n["note"].lower():
                        self.delete_note_by_id(n["id"])
                        return f"Deleted: {n['note']}"
            return "Could not find a matching note to delete."

        if intent == "remind":
            content = text.lower().split("remind", 1)[1].strip()
            now = datetime.now()

            match = re.match(
                r"(?:me\s+)?in\s+(\d+)\s+(second|seconds|minute|minutes|hour|hours)\s+(?:to\s+)?(.+)",
                content,
            )
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                message = match.group(3).strip()

                if "second" in unit:
                    target = now + timedelta(seconds=amount)
                elif "minute" in unit:
                    target = now + timedelta(minutes=amount)
                else:
                    target = now + timedelta(hours=amount)

                with self.lock:
                    with self._connect() as conn:
                        conn.execute(
                            "INSERT INTO reminders (time, message) VALUES (?, ?)",
                            (target.isoformat(), message),
                        )
                        conn.commit()
                return f"Reminder set for {target.strftime('%H:%M:%S')}."

            return "Invalid reminder format. Try: 'remind me in 10 minutes to stretch'."

        return None

    def check_reminders(self) -> list:
        now = datetime.now()
        triggered = []

        with self.lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT id, time, message FROM reminders").fetchall()
                for row in rows:
                    reminder_time = datetime.fromisoformat(row["time"])
                    if now >= reminder_time:
                        triggered.append({"id": row["id"], "time": row["time"], "message": row["message"]})
                        conn.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))
                if triggered:
                    conn.commit()

        return triggered

    def retrieve_relevant(self, query, limit=3):
        notes = self.list_notes()
        query_words = [
            w for w in re.findall(r"\b\w+\b", query.lower()) if w not in STOPWORDS
        ]
        if not query_words:
            return []

        scored = []
        for note in notes:
            text = (note["tag"] + " " + note["note"]).lower()
            score = sum(
                1 for word in query_words if re.search(rf"\b{re.escape(word)}\b", text)
            )
            if score > 0:
                scored.append((score, note))

        scored.sort(reverse=True, key=lambda x: x[0])
        return [n for _, n in scored[:limit]]


def register_tools(registry, memory_module: Module):
    registry.register(
        name="memory_save_note",
        description="Save a persistent note or fact to CREED's local SQLite memory.",
        parameters={
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Short category tag, e.g. general, physics, device"},
                "note": {"type": "string", "description": "The fact or note to remember"},
            },
            "required": ["tag", "note"],
        },
        handler=lambda tag, note: memory_module.handle(
            "remember", f"remember {tag}: {note}", {}
        ),
    )
    registry.register(
        name="memory_recall_notes",
        description="List all saved notes in CREED's persistent memory.",
        parameters={"type": "object", "properties": {}},
        handler=lambda: memory_module.handle("recall", "recall", {}),
    )
    registry.register(
        name="memory_set_reminder",
        description="Schedule a reminder after a number of minutes.",
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Minutes from now"},
                "message": {"type": "string", "description": "Reminder message"},
            },
            "required": ["minutes", "message"],
        },
        handler=lambda minutes, message: memory_module.handle(
            "remind", f"remind in {int(minutes)} minutes {message}", {}
        ),
    )
