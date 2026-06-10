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
        summary_ids = cursor.execute(
            "SELECT id FROM notes WHERE topic = ? AND kind = 'summary'", (topic_slug,)
        ).fetchall()
        summary_ids = {r["id"] for r in summary_ids}

        ids_to_keep = set(summary_ids)
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

        if note_row and kind not in ("turn", "summary"):
            self._auto_link_note(note_row["id"], topic_slug)

        count = self.get_note_count(topic)
        result = {"id": note_id, "title": title or content[:80], "content": content}
        if count >= self.SUMMARIZE_THRESHOLD:
            result["_suggest"] = (
                f"This planet has {count} notes. Consider summarizing via "
                f"`kb planet summarize {topic}` or the summarize_planet MCP tool."
            )
        return result

    def log_chat_to_planet(
        self, folder_name: str, topic: str, content: str, agent_id: str, sender: str = "ai"
    ) -> Optional[str]:
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
        count = self.get_note_count(topic)
        if count >= self.SUMMARIZE_THRESHOLD:
            hint = (
                f"This planet has {count} notes. Consider summarizing via "
                f"`kb planet summarize {topic}` or the summarize_planet MCP tool."
            )
            logger.warning(hint)
            return hint
        return None

    # ── Note linking ─────────────────────────────────────────

    STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such", "no",
        "nor", "not", "only", "own", "same", "so", "than", "too", "very",
        "just", "because", "but", "and", "or", "if", "while", "that", "this",
        "it", "its", "you", "your", "we", "our", "they", "them", "their",
        "i", "me", "my", "he", "him", "his", "she", "her", "who", "whom",
        "which", "what", "about", "up", "down",
        "let", "get", "got", "also", "make", "made",
    }

    @staticmethod
    def _parse_note_id(note_id):
        if isinstance(note_id, int):
            return note_id
        if isinstance(note_id, str):
            if note_id.startswith("note-"):
                try:
                    return int(note_id[5:])
                except ValueError:
                    return None
            try:
                return int(note_id)
            except ValueError:
                return None
        return None

    @staticmethod
    def _tokenize(text):
        import re
        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {w for w in words if w not in SessionManager.STOPWORDS}

    def link_notes(self, from_note_id, to_note_id, link_type="related", weight=1.0):
        from_id = self._parse_note_id(from_note_id)
        to_id = self._parse_note_id(to_note_id)
        if from_id is None or to_id is None:
            return False, "Invalid note ID"
        if from_id == to_id:
            return False, "Cannot link a note to itself"
        from_id, to_id = sorted([from_id, to_id])
        _exec(
            self.storage.connection,
            "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, ?, ?, 1.0, 'explicit')",
            (from_id, to_id, link_type, weight),
        )
        return True, f"Linked note-{from_id} -> note-{to_id} ({link_type})"

    def get_note_neighbors(self, note_id, link_type=None):
        nid = self._parse_note_id(note_id)
        if nid is None:
            return []
        cursor = self.storage.connection.cursor()
        if link_type:
            rows = cursor.execute(
                """SELECT n.id, n.topic, n.kind, n.content, n.title,
                          nl.link_type, nl.weight, nl.confidence, nl.source
                   FROM notes n
                   JOIN note_links nl ON (nl.from_note_id = n.id OR nl.to_note_id = n.id)
                   WHERE (nl.from_note_id = ? OR nl.to_note_id = ?) AND n.id != ?
                   AND nl.link_type = ?""",
                (nid, nid, nid, link_type),
            ).fetchall()
        else:
            rows = cursor.execute(
                """SELECT n.id, n.topic, n.kind, n.content, n.title,
                          nl.link_type, nl.weight, nl.confidence, nl.source
                   FROM notes n
                   JOIN note_links nl ON (nl.from_note_id = n.id OR nl.to_note_id = n.id)
                   WHERE (nl.from_note_id = ? OR nl.to_note_id = ?) AND n.id != ?""",
                (nid, nid, nid),
            ).fetchall()
        # Reinforce: increment weight for each auto-link returned (co-access)
        for nb in rows:
            if nb.get("source") == "auto" and nb.get("link_type") == "auto":
                self.reinforce_link(nid, nb["id"])
        return [dict(r) for r in rows]

    def _auto_link_note(self, note_id, topic_slug):
        cursor = self.storage.connection.cursor()
        new_row = cursor.execute(
            "SELECT id, content FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if not new_row:
            return
        new_words = self._tokenize(new_row["content"])
        if len(new_words) < 3:
            return
        existing = cursor.execute(
            "SELECT id, content FROM notes WHERE topic = ? AND id != ?",
            (topic_slug, note_id),
        ).fetchall()
        for row in existing:
            existing_words = self._tokenize(row["content"])
            if len(existing_words) < 3:
                continue
            intersection = new_words & existing_words
            union = new_words | existing_words
            score = len(intersection) / len(union) if union else 0
            if score >= 0.2:
                from_id, to_id = sorted([note_id, row["id"]])
                weight = round(score, 3)
                confidence = round(min(1.0, score * 1.5), 3)
                _exec(
                    self.storage.connection,
                    "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, 'auto', ?, ?, 'auto')",
                    (from_id, to_id, weight, confidence),
                )

    # ── Agent summarization ──────────────────────────────────

    SUMMARIZE_THRESHOLD = 50

    def get_note_count(self, topic: str) -> int:
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT COUNT(*) AS cnt FROM notes WHERE topic = ?", (topic_slug,)
        ).fetchone()
        return row["cnt"] if row else 0

    def summarize_planet(self, topic: str, limit: int = 50) -> str:
        """Return planet data + notes formatted for an agent to summarize.
        
        Skips existing summary notes to avoid circular summarization.
        Truncates each note to a preview to keep context manageable.
        """
        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            return f"No planet found for '{topic}'."

        all_notes = _get_notes(self.storage.connection, topic_slug)

        # exclude old summaries, limit to N most recent non-summary notes
        source_notes = [n for n in all_notes if n.get("kind") != "summary"]
        source_notes = source_notes[:limit]

        lines = [
            f"# Planet: {row.get('display_topic') or topic_slug}",
            f"Status: {row.get('status', 'active')}",
            f"Memory: {row.get('memory_state', 'hot')}",
            f"Goal: {row.get('goal', '')}",
            f"Current State: {row.get('current_state', '')}",
            f"Notes (showing {len(source_notes)} of {len(all_notes)} total, skipping old summaries):",
            "",
            "--- NOTES (oldest first) ---",
        ]

        for n in reversed(source_notes):
            kind = n.get("kind", "note")
            title = n.get("title") or ""
            content = n.get("content", "")
            created = n.get("created_at", "")
            agent = n.get("agent_id", "default")
            preview = self._trim_text(content, 400)
            lines.append("")
            lines.append(f"[{kind}] {title} ({agent}, {created})")
            if preview != content:
                lines.append(f"{preview} [...truncated]")
            else:
                lines.append(preview)

        lines.extend([
            "",
            "--- END OF NOTES ---",
            "",
            "Write a comprehensive summary of this planet as a single note with kind='summary'.",
            "Cover: goal progress, key decisions, open issues, and next steps.",
            "Call add_note(topic, 'summary', '<your summary>') to save it.",
            f"After saving, call compact_planet(topic) to trim old notes.",
        ])

        return "\n".join(lines)

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

    # ── Planet links ──────────────────────────────────────────

    def link_planets(self, from_topic: str, to_topic: str, relation: str = "related", weight: float = 1.0):
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

    def get_planet_links(self, topic: str):
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

    def remove_planet_link(self, link_id: int):
        _exec(self.storage.connection, "DELETE FROM planet_links WHERE id = ?", (link_id,))

    # ── Edge reinforcement ────────────────────────────────────

    def reinforce_link(self, from_note_id: int, to_note_id: int, increment: float = 0.05):
        from_id, to_id = sorted([from_note_id, to_note_id])
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
            (from_id, to_id),
        ).fetchone()
        if row:
            new_weight = round(min(1.0, row["weight"] + increment), 3)
            _exec(
                self.storage.connection,
                "UPDATE note_links SET weight = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                (new_weight, self._now(), from_id, to_id),
            )

    # ── Background similarity recomputation ────────────────────

    def recompute_links(self, topic: str = None, threshold: float = 0.1, min_weight: float = 0.05):
        cursor = self.storage.connection.cursor()
        if topic:
            notes = cursor.execute(
                "SELECT id, content FROM notes WHERE topic = ?", (self.normalize_topic(topic),)
            ).fetchall()
        else:
            notes = cursor.execute("SELECT id, content FROM notes").fetchall()
        created = 0
        removed = 0
        for i in range(len(notes)):
            for j in range(i + 1, len(notes)):
                wa = self._tokenize(notes[i]["content"])
                wb = self._tokenize(notes[j]["content"])
                if len(wa) < 3 or len(wb) < 3:
                    continue
                intersection = wa & wb
                union = wa | wb
                score = len(intersection) / len(union) if union else 0
                from_id, to_id = sorted([notes[i]["id"], notes[j]["id"]])
                existing = cursor.execute(
                    "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                    (from_id, to_id),
                ).fetchone()
                if score >= threshold:
                    confidence = round(min(1.0, score * 1.5), 3)
                    if existing:
                        new_weight = round((existing["weight"] + score) / 2, 3)
                        _exec(
                            self.storage.connection,
                            "UPDATE note_links SET weight = ?, confidence = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                            (new_weight, confidence, self._now(), from_id, to_id),
                        )
                    else:
                        _exec(
                            self.storage.connection,
                            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, 'auto', ?, ?, 'auto')",
                            (from_id, to_id, round(score, 3), confidence),
                        )
                        created += 1
                elif existing and score < min_weight:
                    _exec(
                        self.storage.connection,
                        "DELETE FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                        (from_id, to_id),
                    )
                    removed += 1
        return {"created": created, "removed": removed, "total_pairs": len(notes) * (len(notes) - 1) // 2}

    # ── Memory tiers ──────────────────────────────────────────

    def set_memory_state(self, topic: str, state: str):
        if state not in ("hot", "warm", "compacted"):
            return False, "State must be hot, warm, or compacted"
        slug = self.normalize_topic(topic)
        _exec(
            self.storage.connection,
            "UPDATE planets SET memory_state = ?, updated_at = ? WHERE topic = ?",
            (state, self._now(), slug),
        )
        return True, f"Planet '{slug}' set to {state}"

    # ── Graph-aware retrieval ─────────────────────────────────

    def get_neighbors_weighted(self, note_id: int, depth: int = 1, min_weight: float = 0.0):
        visited = set()
        results = []
        def traverse(nid, current_depth):
            if nid in visited or current_depth > depth:
                return
            visited.add(nid)
            for nb in self.get_note_neighbors(nid):
                if nb["weight"] and nb["weight"] >= min_weight:
                    nb["_depth"] = current_depth
                    results.append(nb)
                    traverse(nb["id"], current_depth + 1)
        traverse(note_id, 1)
        return results

    def get_subgraph(self, note_id: int, depth: int = 2, min_weight: float = 0.2):
        cursor = self.storage.connection.cursor()
        nid = self._parse_note_id(note_id)
        if nid is None:
            return {"nodes": [], "edges": []}
        node_ids = {nid}
        edges = []
        def traverse(nid, current_depth):
            if current_depth > depth:
                return
            for nb in self.get_note_neighbors(nid):
                if nb["weight"] and nb["weight"] >= min_weight:
                    pair = (nid, nb["id"])
                    if pair not in {(e["source"], e["target"]) for e in edges}:
                        edges.append({"source": nid, "target": nb["id"], "weight": nb["weight"]})
                    if nb["id"] not in node_ids:
                        node_ids.add(nb["id"])
                        traverse(nb["id"], current_depth + 1)
        traverse(nid, 1)
        nodes = []
        for nid in node_ids:
            row = cursor.execute("SELECT id, topic, kind, content, title FROM notes WHERE id = ?", (nid,)).fetchone()
            if row:
                nodes.append(dict(row))
        return {"nodes": nodes, "edges": edges}

    def rank_neighbors(self, note_id: int, by: str = "weight"):
        neighbors = self.get_note_neighbors(note_id)
        if by == "confidence":
            neighbors.sort(key=lambda x: x.get("confidence", 0) or 0, reverse=True)
        else:
            neighbors.sort(key=lambda x: x.get("weight", 0) or 0, reverse=True)
        return neighbors


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
    # Migrate existing tables — add columns that may be missing
    for col, dtype in [("confidence", "REAL DEFAULT 1.0"), ("source", "TEXT DEFAULT 'auto'"), ("updated_at", "TEXT DEFAULT (datetime('now'))")]:
        try:
            conn.execute(f"ALTER TABLE note_links ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    for col, dtype in [("memory_state", "TEXT DEFAULT 'hot'")]:
        try:
            conn.execute(f"ALTER TABLE planets ADD COLUMN {col} {dtype}")
        except Exception:
            pass
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
