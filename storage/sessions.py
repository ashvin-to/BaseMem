"""Session management using planets/notes tables (shared with MCP)."""

import contextlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from models import Node, NodeType

from .config import get_session_timeout_hours
from .db import StorageManager
from .notes import NoteMixin
from storage.db import exec_stmt
from .planets import PlanetMixin
from .tasks import TaskMixin

logger = logging.getLogger(__name__)


class SessionManagerBase:
    SUMMARIZE_THRESHOLD = 50

    def __init__(self, storage: StorageManager):
        self.storage = storage
        _ensure_schema(self.storage.connection)

    @staticmethod
    def normalize_topic(topic: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return slug or "general"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _trim_text(value: str, limit: int = 600) -> str:
        compact = " ".join((value or "").split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _human_age(self, iso_str: str) -> str:
        """Convert ISO timestamp to human-readable age like '2 hours ago'."""
        try:
            dt = datetime.fromisoformat(iso_str)
            delta = datetime.now(timezone.utc) - dt
            secs = int(delta.total_seconds())
            if secs < 60:
                return "moments ago"
            if secs < 3600:
                m = secs // 60
                return f"{m} minute{'s' if m != 1 else ''} ago"
            if secs < 86400:
                h = secs // 3600
                return f"{h} hour{'s' if h != 1 else ''} ago"
            d = secs // 86400
            return f"{d} day{'s' if d != 1 else ''} ago"
        except Exception:
            return "unknown"

    def _render_sessions_block(self, topic_slug: str) -> list[str]:
        """Render a sessions context block. Calls auto_recover_sessions first."""
        lines: list[str] = []
        try:
            if hasattr(self, 'auto_recover_sessions'):
                self.auto_recover_sessions(topic_slug)
        except Exception:
            pass
        if not hasattr(self, 'list_sessions'):
            return lines
        try:
            active = self.list_sessions(topic_slug, status='active')
            if active:
                for s in active[:3]:
                    title = s.get('title', 'untitled')
                    agent = s.get('agent_id', '?')
                    age = self._human_age(s.get('last_active_at', ''))
                    lines.append(f"  session: '{title}' ({agent}) active, last {age}")
        except Exception:
            pass
        try:
            closed_or_paused = self.list_sessions(topic_slug, status='closed')
            closed_or_paused.extend(self.list_sessions(topic_slug, status='paused'))
            if closed_or_paused:
                closed_or_paused.sort(key=lambda s: s.get('last_active_at', ''), reverse=True)
                last = closed_or_paused[0]
                summary = last.get('summary')
                if summary:
                    lines.append(f"  last session: {summary[:300]}")
                else:
                    note_ids = json.loads(last.get('note_ids', '[]'))[-5:]
                    if note_ids:
                        cursor = self.storage.connection.cursor()
                        placeholders = ",".join("?" for _ in note_ids)
                        notes = cursor.execute(
                            f"SELECT title, content FROM notes WHERE id IN ({placeholders}) ORDER BY id ASC",
                            note_ids,
                        ).fetchall()
                        for nr in notes:
                            title = nr['title'] or nr['content'][:80]
                            lines.append(f"  last session note: {title[:200]}")
        except Exception:
            pass
        return lines

    def get_or_create_folder_hub(self, folder_name: str) -> Node:
        title = f"Session: {folder_name}"
        nodes = self.storage.get_all_nodes()
        for node in nodes:
            if node.node_type == NodeType.SUMMARY and node.title == title:
                return node
        node = Node(
            title=title,
            content=f"Global hub for project folder: {folder_name}",
            node_type=NodeType.SUMMARY,
            metadata={"is_folder_hub": True, "folder": folder_name},
        )
        self.storage.add_node(node)
        return node


class SessionManager(PlanetMixin, NoteMixin, TaskMixin, SessionManagerBase):

    # ── Session CRUD ──

    def create_session(self, topic: str, title: str, agent_id: str) -> int:
        topic_slug = self.normalize_topic(topic)
        now = self._now()
        cursor = self.storage.connection.cursor()
        cursor.execute(
            "INSERT INTO sessions (topic, title, agent_id, started_at, last_active_at, note_ids, task_ids) VALUES (?, ?, ?, ?, ?, '[]', '[]')",
            (topic_slug, title, agent_id, now, now),
        )
        self.storage.connection.commit()
        return cursor.lastrowid

    def get_session(self, session_id: int) -> dict | None:
        cursor = self.storage.connection.cursor()
        row = cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, topic: str, status: str | None = None) -> list[dict]:
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        if status:
            rows = cursor.execute(
                "SELECT * FROM sessions WHERE topic = ? AND status = ? ORDER BY started_at DESC",
                (topic_slug, status),
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT * FROM sessions WHERE topic = ? ORDER BY started_at DESC",
                (topic_slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id: int, **kwargs: str) -> bool:
        allowed = {"title", "status", "summary", "agent_id", "note_ids", "task_ids"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False
        updates["last_active_at"] = self._now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [session_id]
        cursor = self.storage.connection.cursor()
        cursor.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", params)
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def close_session(self, session_id: int, summary: str | None = None) -> bool:
        now = self._now()
        cursor = self.storage.connection.cursor()
        if summary:
            cursor.execute(
                "UPDATE sessions SET status = 'closed', ended_at = ?, last_active_at = ?, summary = ? WHERE id = ?",
                (now, now, summary, session_id),
            )
        else:
            cursor.execute(
                "UPDATE sessions SET status = 'closed', ended_at = ?, last_active_at = ? WHERE id = ?",
                (now, now, session_id),
            )
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def pause_session(self, session_id: int) -> bool:
        now = self._now()
        cursor = self.storage.connection.cursor()
        cursor.execute(
            "UPDATE sessions SET status = 'paused', last_active_at = ? WHERE id = ?",
            (now, session_id),
        )
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def resume_session(self, session_id: int, agent_id: str) -> bool:
        now = self._now()
        cursor = self.storage.connection.cursor()
        cursor.execute(
            "UPDATE sessions SET status = 'active', agent_id = ?, last_active_at = ? WHERE id = ?",
            (agent_id, now, session_id),
        )
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def stamp_note(self, session_id: int, note_id: int) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        note_ids = json.loads(session["note_ids"])
        if note_id not in note_ids:
            note_ids.append(note_id)
            self.update_session(session_id, note_ids=json.dumps(note_ids))
        else:
            self.update_session(session_id)
        return True

    def stamp_task(self, session_id: int, task_id: int) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        task_ids = json.loads(session["task_ids"])
        if task_id not in task_ids:
            task_ids.append(task_id)
            self.update_session(session_id, task_ids=json.dumps(task_ids))
        else:
            self.update_session(session_id)
        return True

    def auto_recover_sessions(self, topic: str) -> list[int]:
        topic_slug = self.normalize_topic(topic)
        timeout_hours = get_session_timeout_hours()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        cutoff_str = cutoff.isoformat()
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            "SELECT id, title FROM sessions WHERE topic = ? AND status = 'active' AND last_active_at < ?",
            (topic_slug, cutoff_str),
        ).fetchall()
        recovered: list[int] = []
        for row in rows:
            sid = row["id"]
            title = row["title"]
            now = self._now()
            cursor.execute(
                "UPDATE sessions SET status = 'paused', last_active_at = ? WHERE id = ?",
                (now, sid),
            )
            self.add_note(
                "system", topic_slug, "fact",
                f"Session '{title}' (id={sid}) auto-recovered at {now}: idle > {timeout_hours}h.",
                agent_id="system",
            )
            recovered.append(sid)
        if rows:
            self.storage.connection.commit()
        return recovered

    def get_active_session(self, topic: str, agent_id: str) -> dict | None:
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT * FROM sessions WHERE topic = ? AND status = 'active' AND agent_id = ? ORDER BY last_active_at DESC LIMIT 1",
            (topic_slug, agent_id),
        ).fetchone()
        return dict(row) if row else None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT UNIQUE NOT NULL,
            display_topic TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            goal TEXT DEFAULT '',
            current_state TEXT DEFAULT '',
            next_step TEXT DEFAULT '',
            next_steps TEXT DEFAULT '[]',
            files TEXT DEFAULT '[]',
            commands TEXT DEFAULT '[]',
            handoff TEXT DEFAULT '',
            aliases TEXT DEFAULT '[]',
            memory_state TEXT DEFAULT 'hot',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            title TEXT DEFAULT '',
            agent_id TEXT DEFAULT 'default',
            status TEXT DEFAULT 'open',
            turn_index INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS note_links (
            from_note_id INTEGER NOT NULL,
            to_note_id INTEGER NOT NULL,
            link_type TEXT NOT NULL DEFAULT 'related',
            weight REAL DEFAULT 1.0,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'auto',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (from_note_id, to_note_id, link_type)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'todo',
            priority TEXT NOT NULL DEFAULT 'medium',
            depends_on TEXT DEFAULT '[]',
            files TEXT DEFAULT '[]',
            notes TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS planet_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_planet_id INTEGER NOT NULL,
            to_planet_id INTEGER NOT NULL,
            relation TEXT NOT NULL DEFAULT 'related',
            weight REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(from_planet_id, to_planet_id, relation)
        );
    """)
    for col, dtype in [("confidence", "REAL DEFAULT 1.0"), ("source", "TEXT DEFAULT 'auto'"), ("updated_at", "TEXT DEFAULT (datetime('now'))")]:
        with contextlib.suppress(Exception):
            conn.execute(f"ALTER TABLE note_links ADD COLUMN {col} {dtype}")
    for col, dtype in [("memory_state", "TEXT DEFAULT 'hot'")]:
        with contextlib.suppress(Exception):
            conn.execute(f"ALTER TABLE planets ADD COLUMN {col} {dtype}")
    for col, dtype in [("tags", "TEXT DEFAULT '[]'"), ("pinned", "INTEGER DEFAULT 0")]:
        with contextlib.suppress(Exception):
            conn.execute(f"ALTER TABLE notes ADD COLUMN {col} {dtype}")

    # v2: sessions table + session_id on notes/tasks
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,
            ended_at TEXT,
            last_active_at TEXT NOT NULL,
            summary TEXT,
            agent_id TEXT NOT NULL,
            note_ids TEXT NOT NULL DEFAULT '[]',
            task_ids TEXT NOT NULL DEFAULT '[]'
        );
    """)
    for col, dtype in [("session_id", "INTEGER")]:
        with contextlib.suppress(Exception):
            conn.execute(f"ALTER TABLE notes ADD COLUMN {col} {dtype}")
        with contextlib.suppress(Exception):
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {dtype}")
    conn.commit()
