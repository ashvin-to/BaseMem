"""Session management using planets/notes tables (shared with MCP)."""

import contextlib
import logging
import re
import sqlite3
from datetime import datetime, timezone

from models import Node, NodeType

from .db import StorageManager
from .notes import NoteMixin
from .planets import (
    PlanetMixin,
)
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
    pass


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
    conn.commit()
