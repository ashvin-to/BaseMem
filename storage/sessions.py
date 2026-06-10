"""Session management using planets/notes tables (shared with MCP)."""

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from modelsimport Node, Edge, NodeType, EdgeType
from .db import StorageManager

logger = logging.getLogger(__name__)


class _PlanetProxy:
    """Backward-compatible wrapper around a planets table row."""

    def __init__(self, row: dict, notes: Optional[list] = None):
        self._row = row
        self._notes = notes or []

    @property
    def id(self) -> str:
        return f"planet-{self._row['topic']}"

    @property
    def title(self) -> str:
        return self._row.get("display_topic") or self._row["topic"]

    @property
    def content(self) -> str:
        return _render_planet_content(
            self._row.get("display_topic") or self._row["topic"],
            self.metadata,
        )

    @property
    def metadata(self) -> Dict[str, Any]:
        row = self._row
        def _sj(v):
            return json.loads(v) if v and v.strip() else []
        next_steps = _sj(row.get("next_steps"))
        files = _sj(row.get("files"))
        commands = _sj(row.get("commands"))
        aliases = _sj(row.get("aliases"))

        activity = [
            {"timestamp": n.get("created_at", ""), "agent_id": n.get("agent_id", "unknown"),
             "sender": n.get("agent_id", "ai"), "message": n["content"]}
            for n in self._notes if n.get("kind") == "turn"
        ]

        note_list = [
            {"id": f"note-{n.get('id')}", "kind": n.get("kind"), "title": n.get("title") or n["content"][:80],
             "content": n["content"], "status": n.get("status", "open"), "agent_id": n.get("agent_id", "default")}
            for n in self._notes if n.get("kind") != "turn"
        ]

        return {
            "topic": row["topic"],
            "display_topic": row.get("display_topic") or row["topic"],
            "status": row.get("status", "active"),
            "goal": row.get("goal", ""),
            "current_state": row.get("current_state", ""),
            "next_steps": next_steps,
            "next_step": row.get("next_step", ""),
            "files": files,
            "commands": commands,
            "handoff": row.get("handoff", ""),
            "aliases": aliases,
            "notes": note_list,
            "recent_activity": activity,
            "is_task_planet": True,
            "scope": "planet",
            "updated_at": row.get("updated_at", ""),
            "created_at": row.get("created_at", ""),
        }

    def __bool__(self):
        return True


def _render_planet_content(topic: str, metadata: Dict[str, Any]) -> str:
    activity = metadata.get("recent_activity", [])
    notes = metadata.get("notes", [])
    files = metadata.get("files", [])
    commands = metadata.get("commands", [])
    next_steps = metadata.get("next_steps", [])
    decisions = [n for n in notes if n.get("kind") == "decision"]
    issues = [n for n in notes if n.get("kind") in {"issue", "question"} and n.get("status") != "done"]

    activity_lines = [
        f"- {item.get('timestamp', '')} {item.get('agent_id', 'unknown')}: {item.get('message', '')}"
        for item in activity[-8:]
    ]
    decision_lines = [f"- {n.get('content') or n.get('title')}" for n in decisions[-8:]]
    issue_lines = [f"- {n.get('content') or n.get('title')}" for n in issues[-8:]]

    return "\n".join([
        f"# Topic: {topic}",
        "",
        "## Goal",
        metadata.get("goal") or "Not set.",
        "",
        "## Status",
        metadata.get("status") or "active",
        "",
        "## Current State",
        metadata.get("current_state") or "No current state recorded.",
        "",
        "## Decisions",
        "\n".join(decision_lines) if decision_lines else "- None",
        "",
        "## Open Issues",
        "\n".join(issue_lines) if issue_lines else "- None",
        "",
        "## Next Steps",
        "\n".join(f"- {s}" for s in next_steps) if next_steps else "- None",
        "",
        "## Important Files",
        "\n".join(f"- {f}" for f in files) if files else "- None",
        "",
        "## Commands",
        "\n".join(f"- {c}" for c in commands) if commands else "- None",
        "",
        "## Recent Activity",
        "\n".join(activity_lines) if activity_lines else "- None",
        "",
        "## Agent Handoff",
        metadata.get("handoff") or "Read this planet first. Open moons only when detailed transcript history is needed.",
    ])


class SessionManager:
    """
    3-Tier Hierarchy:
    Sun (Tier 1): Folder Hub — stored in nodes table
    Planet (Tier 2): Shared Task/Topic — stored in planets table
    Moon (Tier 3): Private Agent-Session Archives — stored in nodes table
    """

    def __init__(self, storage: StorageManager):
        self.storage = storage
        _ensure_schema(self.storage.connection)

    @staticmethod
    def normalize_topic(topic: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return slug or "general"

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _trim_text(value: str, limit: int = 600) -> str:
        compact = " ".join((value or "").split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    # ── Folder Hub (Sun) — stays on nodes table ──────────────

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

    # ── Planet operations (planets table) ────────────────────

    def get_or_create_task_planet(self, folder_name: str, topic: str) -> _PlanetProxy:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)

        if row:
            aliases = set(json.loads(row["aliases"]) if row["aliases"] and row["aliases"].strip() else [])
            aliases.update({topic, topic_slug})
            _exec(
                self.storage.connection,
                "UPDATE planets SET display_topic = ?, aliases = ?, updated_at = ? WHERE topic = ?",
                (row["display_topic"] or topic, json.dumps(sorted(aliases)), self._now(), topic_slug),
            )
        else:
            _exec(
                self.storage.connection,
                "INSERT INTO planets (topic, display_topic, aliases, current_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (topic_slug, topic, json.dumps(sorted({topic, topic_slug})),
                 f"Unified task context for: {topic}", self._now(), self._now()),
            )

        row = _get_planet_row(self.storage.connection, topic_slug)
        notes = _get_notes(self.storage.connection, topic_slug)
        return _PlanetProxy(row, notes)

    def update_planet(
        self,
        folder_name: str,
        topic: str,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        current_state: Optional[str] = None,
        next_step: Optional[str] = None,
        file_path: Optional[str] = None,
        command: Optional[str] = None,
        handoff: Optional[str] = None,
    ) -> _PlanetProxy:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
            row = _get_planet_row(self.storage.connection, topic_slug)

        updates = []
        params: list = []
        if status is not None:
            updates.append("status = ?"); params.append(status)
        if goal is not None:
            updates.append("goal = ?"); params.append(goal)
        if current_state is not None:
            updates.append("current_state = ?"); params.append(current_state)
        if next_step is not None:
            raw = row.get("next_steps")
            steps = set(json.loads(raw) if raw and raw.strip() else [])
            steps.add(next_step)
            updates.append("next_steps = ?"); params.append(json.dumps(sorted(steps)))
        if file_path is not None:
            raw = row.get("files")
            files = set(json.loads(raw) if raw and raw.strip() else [])
            files.add(file_path)
            updates.append("files = ?"); params.append(json.dumps(sorted(files)))
        if command is not None:
            raw = row.get("commands")
            commands = set(json.loads(raw) if raw and raw.strip() else [])
            commands.add(command)
            updates.append("commands = ?"); params.append(json.dumps(sorted(commands)))
        if handoff is not None:
            updates.append("handoff = ?"); params.append(handoff)

        if updates:
            updates.append("updated_at = ?"); params.append(self._now())
            params.append(topic_slug)
            _exec(
                self.storage.connection,
                f"UPDATE planets SET {', '.join(updates)} WHERE topic = ?",
                params,
            )

        row = _get_planet_row(self.storage.connection, topic_slug)
        notes = _get_notes(self.storage.connection, topic_slug)
        return _PlanetProxy(row, notes)

    def get_planet(self, topic: str) -> Optional[_PlanetProxy]:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            return None
        notes = _get_notes(self.storage.connection, topic_slug)
        return _PlanetProxy(row, notes)

    def get_active_planet(self) -> Optional[_PlanetProxy]:
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT * FROM planets ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        notes = _get_notes(self.storage.connection, row["topic"])
        return _PlanetProxy(dict(row), notes)

    def delete_planet(self, topic: str) -> bool:
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        cursor.execute("DELETE FROM planets WHERE topic = ?", (topic_slug,))
        cursor.execute("DELETE FROM notes WHERE topic = ?", (topic_slug,))
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def compact_planet(self, folder_name: str, topic: str, agent_id: str = "default") -> _PlanetProxy:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
        cursor = self.storage.connection.cursor()
        cursor.execute(
            "DELETE FROM notes WHERE topic = ? AND id NOT IN (SELECT id FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 30)",
            (topic_slug, topic_slug),
        )
        _exec(
            self.storage.connection,
            "UPDATE planets SET updated_at = ? WHERE topic = ?",
            (self._now(), topic_slug),
        )
        row = _get_planet_row(self.storage.connection, topic_slug)
        notes = _get_notes(self.storage.connection, topic_slug)
        return _PlanetProxy(row, notes)

    # ── Note operations (notes table) ────────────────────────

    def add_note(
        self,
        folder_name: str,
        topic: str,
        kind: str,
        content: str,
        agent_id: str = "default",
        title: Optional[str] = None,
        status: str = "open",
    ) -> dict:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)

        kind = kind.lower().strip() or "fact"
        now = self._now()
        _exec(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, title, agent_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (topic_slug, kind, content, title or content[:80], agent_id, status, now, now),
        )
        _exec(
            self.storage.connection,
            "UPDATE planets SET updated_at = ? WHERE topic = ?",
            (now, topic_slug),
        )

        cursor = self.storage.connection.cursor()
        note_row = cursor.execute(
            "SELECT id, topic, kind, content, title, agent_id, status FROM notes WHERE topic = ? AND created_at = ? AND content = ? LIMIT 1",
            (topic_slug, now, content),
        ).fetchone()

        note_id = f"note-{note_row['id']}" if note_row else f"note-{topic_slug}-{uuid.uuid4().hex[:8]}"
        return {"id": note_id, "title": title or content[:80], "content": content}

    def log_chat_to_planet(
        self, folder_name: str, topic: str, content: str, agent_id: str, sender: str = "ai"
    ) -> None:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
        now = self._now()
        _exec(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, agent_id, status, created_at, updated_at) VALUES (?, 'turn', ?, ?, 'open', ?, ?)",
            (topic_slug, content, agent_id, now, now),
        )
        _exec(
            self.storage.connection,
            "UPDATE planets SET updated_at = ? WHERE topic = ?",
            (now, topic_slug),
        )

    # ── Context builder ──────────────────────────────────────

    def build_agent_context(
        self, topic: str, query: Optional[str] = None, result_limit: int = 5
    ) -> str:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)

        if not row:
            return "\n".join([
                "# Knowledge Base Context",
                f"Topic: {topic_slug}",
                "",
                "No stored context found for this topic yet.",
                "If you make durable decisions, create notes or log a turn after responding.",
            ])

        notes = _get_notes(self.storage.connection, topic_slug)
        proxy = _PlanetProxy(row, notes)
        metadata = proxy.metadata

        lines = [
            "# Knowledge Base Context",
            f"Topic: {metadata.get('display_topic') or topic_slug}",
            f"Status: {metadata.get('status', 'active')}",
            "",
            "## Goal",
            self._trim_text(metadata.get("goal") or "Not set.", 300),
            "",
            "## Current State",
            self._trim_text(metadata.get("current_state") or "No current state recorded.", 500),
        ]

        next_steps = metadata.get("next_steps", [])
        if next_steps:
            lines.extend([
                "",
                "## Next Steps",
                *[f"- {self._trim_text(step, 180)}" for step in next_steps[-5:]],
            ])

        all_notes = metadata.get("notes", [])
        if all_notes:
            lines.extend([
                "",
                "## Key Notes",
                *[
                    f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 220)}"
                    for n in all_notes[-8:]
                ],
            ])

        activity = metadata.get("recent_activity", [])
        if activity:
            lines.extend([
                "",
                "## Recent Activity",
                *[
                    f"- {item.get('agent_id', 'unknown')} ({item.get('sender', 'ai')}): {self._trim_text(item.get('message', ''), 220)}"
                    for item in activity[-6:]
                ],
            ])

        if query:
            related_ids = self.storage.search_nodes_fts(
                f"{topic_slug} {query}", limit=result_limit * 3
            )
            related_nodes = []
            for node_id in related_ids:
                node = self.storage.get_node(node_id)
                if not node:
                    continue
                related_nodes.append(node)
                if len(related_nodes) >= result_limit:
                    break

            if related_nodes:
                lines.extend([
                    "",
                    "## Query-Relevant Memories",
                    *[
                        f"- [{node.node_type.value}] {node.title}: {self._trim_text(node.content, 220)}"
                        for node in related_nodes
                    ],
                ])

        handoff = metadata.get("handoff")
        if handoff:
            lines.extend([
                "",
                "## Handoff",
                self._trim_text(handoff, 400),
            ])

        lines.extend([
            "",
            "## Instructions",
            "- Use this memory before answering.",
            "- Prefer existing decisions unless the user asks to revisit them.",
            "- After answering, log durable updates back into the knowledge base.",
        ])

        return "\n".join(lines)

    # ── Moon / Archive (still uses nodes table) ────────────

    def ingest_archive_moon(
        self, folder_name: str, topic: str, full_transcript: str, agent_id: str
    ) -> Optional[Node]:
        topic_slug = self.normalize_topic(topic)
        planet_row = _get_planet_row(self.storage.connection, topic_slug)

        if not planet_row:
            logger.warning(
                f"Archive rejected: No existing planet found for topic '{topic}'. Start a turn first."
            )
            return None

        timestamp = self._now()
        moon_id = f"archive-{agent_id}-{topic_slug}-{uuid.uuid4().hex[:8]}"

        moon_node = Node(
            id=moon_id,
            title=f"History ({agent_id}): {topic_slug}",
            content=full_transcript,
            node_type=NodeType.CONVERSATION,
            keywords=[topic_slug, agent_id, "archive", "moon"],
            metadata={
                "topic": topic_slug,
                "agent_id": agent_id,
                "is_private_moon": True,
                "scope": "moon",
                "synced_at": timestamp,
            },
        )
        self.storage.add_node(moon_node)

        _exec(
            self.storage.connection,
            "UPDATE planets SET updated_at = ? WHERE topic = ?",
            (timestamp, topic_slug),
        )
        _exec(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, agent_id, created_at, updated_at) VALUES (?, 'turn', ?, ?, ?, ?)",
            (topic_slug, f"Archived moon {moon_id}.", agent_id, timestamp, timestamp),
        )

        return moon_node

    def get_neighbors(self, node_id: str):
        return self.storage.get_neighbors(node_id)


# ── Module-level helpers ──────────────────────────────────

_SCHEMA_INITIALIZED: set = set()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    key = id(conn)
    if key in _SCHEMA_INITIALIZED:
        return
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
    """)
    conn.commit()
    _SCHEMA_INITIALIZED.add(key)


def _get_planet_row(conn: sqlite3.Connection, topic: str) -> Optional[dict]:
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM planets WHERE topic = ?", (topic,)).fetchone()
    return dict(row) if row else None


def _get_notes(conn: sqlite3.Connection, topic: str) -> list:
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 100",
        (topic,),
    ).fetchall()
    return [dict(r) for r in rows]


def _exec(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    conn.execute(sql, params)
    conn.commit()
