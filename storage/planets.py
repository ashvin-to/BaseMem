"""Planet operations — shared task/topic context stored in planets table."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from models import Node, NodeType

if TYPE_CHECKING:
    from storage.db import StorageManager

logger = logging.getLogger(__name__)


def _get_planet_row(conn: sqlite3.Connection, topic: str) -> dict | None:
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM planets WHERE topic = ?", (topic,)).fetchone()
    return dict(row) if row else None


def _get_notes(conn: sqlite3.Connection, topic: str, limit: int = 100) -> list:
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT ?",
        (topic, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_planet(conn: sqlite3.Connection, topic_slug: str) -> _PlanetProxy | None:
    row = _get_planet_row(conn, topic_slug)
    if not row:
        return None
    notes = _get_notes(conn, topic_slug)
    return _PlanetProxy(row, notes)


def _render_planet_content(topic: str, metadata: dict[str, Any]) -> str:
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


class _PlanetProxy:
    """Backward-compatible wrapper around a planets table row."""

    def __init__(self, row: dict, notes: list | None = None):
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
    def metadata(self) -> dict[str, Any]:
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
             "content": n["content"], "status": n.get("status", "open"), "agent_id": n.get("agent_id", "default"),
             "pinned": bool(n.get("pinned", 0)),
             "tags": json.loads(n.get("tags", "[]")) if isinstance(n.get("tags"), str) else (n.get("tags") or [])}
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


class PlanetMixin:
    """Mixin providing planet CRUD methods. Requires self.storage (StorageManager)."""

    storage: StorageManager
    normalize_topic: Any
    _now: Any

    def get_or_create_task_planet(self, _folder_name: str, topic: str) -> _PlanetProxy:
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

        result = _get_planet(self.storage.connection, topic_slug)
        assert result is not None
        return result

    def update_planet(
        self,
        _folder_name: str,
        topic: str,
        status: str | None = None,
        goal: str | None = None,
        current_state: str | None = None,
        next_step: str | None = None,
        file_path: str | None = None,
        command: str | None = None,
        handoff: str | None = None,
    ) -> _PlanetProxy:
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
            row = _get_planet_row(self.storage.connection, topic_slug)

        assert row is not None  # guaranteed by get_or_create_task_planet

        updates = []
        params: list = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if goal is not None:
            updates.append("goal = ?")
            params.append(goal)
        if current_state is not None:
            updates.append("current_state = ?")
            params.append(current_state)
        if next_step is not None:
            raw = row.get("next_steps")
            steps = set(json.loads(raw) if raw and raw.strip() else [])
            steps.add(next_step)
            updates.append("next_steps = ?")
            params.append(json.dumps(sorted(steps)))
        if file_path is not None:
            raw = row.get("files")
            files = set(json.loads(raw) if raw and raw.strip() else [])
            files.add(file_path)
            updates.append("files = ?")
            params.append(json.dumps(sorted(files)))
        if command is not None:
            raw = row.get("commands")
            commands = set(json.loads(raw) if raw and raw.strip() else [])
            commands.add(command)
            updates.append("commands = ?")
            params.append(json.dumps(sorted(commands)))
        if handoff is not None:
            updates.append("handoff = ?")
            params.append(handoff)

        if updates:
            updates.append("updated_at = ?")
            params.append(self._now())
            params.append(topic_slug)
            _exec(
                self.storage.connection,
                f"UPDATE planets SET {', '.join(updates)} WHERE topic = ?",
                params,
            )

        result = _get_planet(self.storage.connection, topic_slug)
        assert result is not None
        return result

    def get_planet(self, topic: str) -> _PlanetProxy | None:
        topic_slug = self.normalize_topic(topic)
        return _get_planet(self.storage.connection, topic_slug)

    def get_active_planet(self) -> _PlanetProxy | None:
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT * FROM planets ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return _get_planet(self.storage.connection, row["topic"])

    def delete_planet(self, topic: str) -> bool:
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        cursor.execute("DELETE FROM planets WHERE topic = ?", (topic_slug,))
        cursor.execute("DELETE FROM notes WHERE topic = ?", (topic_slug,))
        self.storage.connection.commit()
        return cursor.rowcount > 0

    def compact_planet(self, _folder_name: str, topic: str, _agent_id: str = "default") -> _PlanetProxy:
        import contextlib

        from .tasks import _get_tasks

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)

        cursor = self.storage.connection.cursor()
        summary_ids = {r["id"] for r in cursor.execute(
            "SELECT id FROM notes WHERE topic = ? AND kind = 'summary'", (topic_slug,)
        ).fetchall()}

        pinned = cursor.execute(
            "SELECT id FROM notes WHERE topic = ? AND pinned = 1", (topic_slug,)
        ).fetchall()

        ids_to_keep = set(summary_ids) | {r["id"] for r in pinned}

        task_notes = set()
        for t in _get_tasks(cursor.connection, topic_slug):
            if t.get("status") and t["status"] != "done":
                nids = json.loads(t.get("notes", "[]"))
                for nid in nids:
                    with contextlib.suppress(ValueError, TypeError):
                        task_notes.add(int(nid))
        ids_to_keep.update(task_notes)

        recent = cursor.execute(
            "SELECT id FROM notes WHERE topic = ? AND kind != 'summary' ORDER BY created_at DESC LIMIT 30",
            (topic_slug,),
        ).fetchall()
        ids_to_keep.update(r["id"] for r in recent)

        if ids_to_keep:
            placeholders = ",".join("?" for _ in ids_to_keep)
            cursor.execute(
                f"DELETE FROM notes WHERE topic = ? AND id NOT IN ({placeholders})",
                (topic_slug, *ids_to_keep),
            )
        else:
            cursor.execute("DELETE FROM notes WHERE topic = ?", (topic_slug,))

        _exec(
            self.storage.connection,
            "UPDATE planets SET memory_state = 'compacted', updated_at = ? WHERE topic = ?",
            (self._now(), topic_slug),
        )
        result = _get_planet(self.storage.connection, topic_slug)
        assert result is not None
        return result

    def link_planets(self, from_topic: str, to_topic: str, relation: str = "related", weight: float = 1.0) -> tuple[bool, str]:
        from_slug = self.normalize_topic(from_topic)
        to_slug = self.normalize_topic(to_topic)
        if from_slug == to_slug:
            return False, "Cannot link a planet to itself"
        from_row = _get_planet_row(self.storage.connection, from_slug)
        to_row = _get_planet_row(self.storage.connection, to_slug)
        if not from_row:
            return False, f"Planet '{from_topic}' not found"
        if not to_row:
            return False, f"Planet '{to_topic}' not found"
        from_id, to_id = sorted([from_row["id"], to_row["id"]])
        _exec(
            self.storage.connection,
            "INSERT OR IGNORE INTO planet_links (from_planet_id, to_planet_id, relation, weight) VALUES (?, ?, ?, ?)",
            (from_id, to_id, relation, weight),
        )
        return True, f"Linked planet '{from_slug}' -> '{to_slug}' ({relation})"

    def get_planet_links(self, topic: str) -> list[dict]:
        slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, slug)
        if not row:
            return []
        pid = row["id"]
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            """SELECT pl.id, pl.from_planet_id, pl.to_planet_id, pl.relation, pl.weight,
                      p1.topic AS from_topic, p2.topic AS to_topic
               FROM planet_links pl
               JOIN planets p1 ON p1.id = pl.from_planet_id
               JOIN planets p2 ON p2.id = pl.to_planet_id
               WHERE pl.from_planet_id = ? OR pl.to_planet_id = ?""",
            (pid, pid),
        ).fetchall()
        result = []
        for r in rows:
            other = r["to_topic"] if r["from_planet_id"] == pid else r["from_topic"]
            result.append({
                "id": r["id"],
                "planet": other,
                "relation": r["relation"],
                "weight": r["weight"],
            })
        return result

    def get_all_planet_links(self) -> list[dict]:
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            """SELECT pl.from_planet_id, pl.to_planet_id, pl.relation, pl.weight,
                      p1.topic AS from_topic, p2.topic AS to_topic
               FROM planet_links pl
               JOIN planets p1 ON p1.id = pl.from_planet_id
               JOIN planets p2 ON p2.id = pl.to_planet_id"""
        ).fetchall()
        return [dict(r) for r in rows]

    def list_planets(self) -> list[dict]:
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM planets ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_memory_state(self, topic: str, state: str) -> tuple[bool, str]:
        if state not in ("hot", "warm", "compacted"):
            return False, "State must be hot, warm, or compacted"
        slug = self.normalize_topic(topic)
        _exec(
            self.storage.connection,
            "UPDATE planets SET memory_state = ?, updated_at = ? WHERE topic = ?",
            (state, self._now(), slug),
        )
        return True, f"Planet '{slug}' set to {state}"

    def get_context(self, topic: str, query: str = "") -> str:
        """Compact pre-answer context: state, next step, decisions, facts."""
        topic_slug = self.normalize_topic(topic)
        conn = self.storage.connection
        lines = [f"ctx: {topic_slug}"]
        q = query.strip().lower()

        from .tasks import _get_tasks

        row = _get_planet_row(conn, topic_slug)
        if row:
            if row.get("current_state"):
                lines.append(f"  state: {row['current_state']}")
            if row.get("next_step"):
                lines.append(f"  next: {row['next_step']}")
        else:
            lines.append("  state: (no context yet)")
            cursor = conn.cursor()
            topics = cursor.execute(
                "SELECT topic FROM planets WHERE topic LIKE ? LIMIT 5",
                (f"%{topic_slug}%",),
            ).fetchall()
            if topics:
                names = ", ".join(r[0] for r in topics)
                lines.append(f"  (did you mean: {names})")

        tasks = _get_tasks(conn, topic_slug)
        open_tasks = [t for t in tasks if t.get("status") and t["status"] != "done"]
        if open_tasks:
            lines.append("")
            lines.append(f"  tasks ({len(open_tasks)} open):")
            for t in open_tasks[:5]:
                lines.append(f"    task-{t['id']} [{t['status']}/{t['priority']}] {t['title']}")
            if len(open_tasks) > 5:
                lines.append(f"    ... and {len(open_tasks) - 5} more")

        notes = _get_notes(conn, topic_slug)
        pinned = [n for n in notes if n.get("pinned")]
        for n in pinned:
            lines.append(f"  pin: {n['content'][:300]}")
        for n in notes:
            if n.get("kind") in ("decision", "issue", "fact") and (not q or q in (n.get("content") or "").lower()):
                tag = {"decision": "dec", "issue": "iss", "fact": "fact"}.get(n["kind"], "note")
                lines.append(f"  {tag}: {n['content'][:300]}")

        return "\n".join(lines)

    def ingest_archive_moon(
        self, _folder_name: str, topic: str, full_transcript: str, agent_id: str
    ) -> Node | None:
        import uuid

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

    def get_neighbors(self, node_id: str) -> list[str]:
        return self.storage.get_neighbors(node_id)

    def export_kb(self, planet: str | None = None) -> dict:
        cursor = self.storage.connection.cursor()
        data: dict[str, Any] = {"version": 1, "planets": [], "notes": [], "note_links": [], "planet_links": []}
        rows = cursor.execute("SELECT * FROM planets").fetchall()
        for r in rows:
            p = dict(r)
            if planet and p["topic"] != planet:
                continue
            data["planets"].append(p)
        if planet:
            topic = self.normalize_topic(planet)
            data["notes"] = [dict(r) for r in cursor.execute("SELECT * FROM notes WHERE topic = ?", (topic,)).fetchall()]
            note_ids = [n["id"] for n in data["notes"]]
            if note_ids:
                ph = ",".join("?" for _ in note_ids)
                data["note_links"] = [
                    dict(r) for r in cursor.execute(
                        f"SELECT * FROM note_links WHERE from_note_id IN ({ph}) OR to_note_id IN ({ph})", note_ids + note_ids
                    ).fetchall()
                ]
        else:
            data["notes"] = [dict(r) for r in cursor.execute("SELECT * FROM notes").fetchall()]
            data["note_links"] = [dict(r) for r in cursor.execute("SELECT * FROM note_links").fetchall()]
            data["planet_links"] = [dict(r) for r in cursor.execute("SELECT * FROM planet_links").fetchall()]
        return data

    def import_kb(self, data: dict) -> dict:
        cursor = self.storage.connection.cursor()
        stats: dict = {"planets_created": 0, "planets_skipped": 0, "notes_created": 0, "notes_skipped": 0, "note_links": 0, "planet_links": 0, "errors": []}
        for p in data.get("planets", []):
            try:
                cursor.execute((
                    "INSERT OR IGNORE INTO planets "
                    "(topic, display_topic, status, goal, current_state, next_step, next_steps, "
                    "files, commands, handoff, aliases, memory_state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                    (p["topic"], p.get("display_topic", ""), p.get("status", "active"), p.get("goal", ""),
                     p.get("current_state", ""), p.get("next_step", ""), p.get("next_steps", "[]"),
                     p.get("files", "[]"), p.get("commands", "[]"), p.get("handoff", ""),
                     p.get("aliases", "[]"), p.get("memory_state", "hot")),
                )
                if cursor.rowcount:
                    stats["planets_created"] += 1
                else:
                    stats["planets_skipped"] += 1
            except Exception as e:
                stats["errors"].append(f"planet {p.get('topic')}: {e}")
        for n in data.get("notes", []):
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO notes (id, topic, kind, content, title, agent_id, status, turn_index) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (n["id"], n["topic"], n.get("kind", "fact"), n["content"], n.get("title", ""),
                     n.get("agent_id", "default"), n.get("status", "open"), n.get("turn_index", 0)),
                )
                if cursor.rowcount:
                    stats["notes_created"] += 1
                else:
                    stats["notes_skipped"] += 1
            except Exception as e:
                stats["errors"].append(f"note {n.get('id')}: {e}")
        for nl in data.get("note_links", []):
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (nl["from_note_id"], nl["to_note_id"], nl.get("link_type", "related"),
                     nl.get("weight", 1.0), nl.get("confidence", 1.0), nl.get("source", "auto")),
                )
                if cursor.rowcount:
                    stats["note_links"] += 1
            except Exception as e:
                stats["errors"].append(f"note_link {nl.get('from_note_id')}->{nl.get('to_note_id')}: {e}")
        for pl in data.get("planet_links", []):
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO planet_links (from_planet_id, to_planet_id, relation, weight) "
                    "VALUES (?, ?, ?, ?)",
                    (pl["from_planet_id"], pl["to_planet_id"], pl.get("relation", "related"), pl.get("weight", 1.0)),
                )
                if cursor.rowcount:
                    stats["planet_links"] += 1
            except Exception as e:
                stats["errors"].append(f"planet_link {pl.get('from_planet_id')}->{pl.get('to_planet_id')}: {e}")
        self.storage.connection.commit()
        return stats

    def get_planet_dict(self, topic: str) -> dict | None:
        slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, slug)
        if not row:
            return None
        return dict(row)

    def get_planet_with_notes(self, topic: str, note_limit: int = 50) -> dict | None:
        slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, slug)
        if not row:
            return None
        notes = _get_notes(self.storage.connection, slug, limit=note_limit)
        result = dict(row)
        result["notes"] = notes
        return result


def _exec(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> None:
    conn.execute(sql, params)
    conn.commit()
