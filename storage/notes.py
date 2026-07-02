"""Note operations — durable facts, decisions, issues stored in notes table."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from storage.db import StorageManager

logger = logging.getLogger(__name__)


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


def _exec(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> None:
    conn.execute(sql, params)
    conn.commit()


class NoteMixin:
    """Mixin providing note CRUD and linking methods. Requires self.storage (StorageManager)."""

    storage: StorageManager
    normalize_topic: Any
    _now: Any
    _trim_text: Any
    get_or_create_task_planet: Any

    SUMMARIZE_THRESHOLD = 50

    @staticmethod
    def _parse_note_id(note_id: int | str) -> int | None:
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
    def _tokenize(text: str) -> set[str]:
        import re
        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {w for w in words if w not in STOPWORDS}

    def add_note(
        self,
        _folder_name: str,
        topic: str,
        kind: str,
        content: str,
        agent_id: str = "default",
        title: str | None = None,
        status: str = "open",
    ) -> dict:
        from .planets import _exec as _pexec
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)

        kind = kind.lower().strip() or "fact"
        now = self._now()
        _pexec(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, title, agent_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (topic_slug, kind, content, title or content[:80], agent_id, status, now, now),
        )
        _pexec(
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
        self, _folder_name: str, topic: str, content: str, agent_id: str, _sender: str = "ai"
    ) -> str | None:
        from .planets import _exec as _pexec
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
        now = self._now()
        _pexec(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, agent_id, status, created_at, updated_at) VALUES (?, 'turn', ?, ?, 'open', ?, ?)",
            (topic_slug, content, agent_id, now, now),
        )
        _pexec(
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

    def link_notes(
        self, from_note_id: int | str, to_note_id: int | str, link_type: str = "related", weight: float = 1.0
    ) -> tuple[bool, str]:
        from .planets import _exec as _pexec

        from_id = self._parse_note_id(from_note_id)
        to_id = self._parse_note_id(to_note_id)
        if from_id is None or to_id is None:
            return False, "Invalid note ID"
        if from_id == to_id:
            return False, "Cannot link a note to itself"
        from_id, to_id = sorted([from_id, to_id])
        _pexec(
            self.storage.connection,
            "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, ?, ?, 1.0, 'explicit')",
            (from_id, to_id, link_type, weight),
        )
        return True, f"Linked note-{from_id} -> note-{to_id} ({link_type})"

    def get_note_neighbors(self, note_id: int | str, link_type: str | None = None) -> list[dict]:
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
        rows = [dict(r) for r in rows]
        for nb in rows:
            if nb.get("source") == "auto" and nb.get("link_type") == "auto":
                self.reinforce_link(nid, nb["id"])
        return rows

    def _auto_link_note(self, note_id: int, topic_slug: str) -> None:
        from .planets import _exec as _pexec

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
                _pexec(
                    self.storage.connection,
                    "INSERT OR IGNORE INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, 'auto', ?, ?, 'auto')",
                    (from_id, to_id, weight, confidence),
                )

    def get_note_count(self, topic: str) -> int:

        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT COUNT(*) AS cnt FROM notes WHERE topic = ?", (topic_slug,)
        ).fetchone()
        return row["cnt"] if row else 0

    def summarize_planet(self, topic: str, limit: int = 50) -> str:
        """Return planet data + notes formatted for an agent to summarize."""
        from .planets import _get_notes, _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            return f"No planet found for '{topic}'."

        all_notes = _get_notes(self.storage.connection, topic_slug)

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
            "After saving, call compact_planet(topic) to trim old notes.",
        ])

        return "\n".join(lines)

    def build_agent_context(
        self, topic: str, query: str | None = None, result_limit: int = 5
    ) -> str:
        from .planets import _get_planet

        topic_slug = self.normalize_topic(topic)
        proxy = _get_planet(self.storage.connection, topic_slug)
        if not proxy:
            return "\n".join([
                "# Knowledge Base Context",
                f"Topic: {topic_slug}",
                "",
                "No stored context found for this topic yet.",
                "If you make durable decisions, create notes or log a turn after responding.",
            ])

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
        pinned_notes = [n for n in all_notes if n.get("pinned")]
        if pinned_notes:
            lines.extend([
                "",
                "## Pinned Notes",
                *[
                    f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 220)}"
                    for n in pinned_notes
                ],
            ])

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

    def get_note(self, note_id: int) -> dict | None:
        cursor = self.storage.connection.cursor()
        row = cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    def search_notes(
        self, topic: str, kind: str = "", query: str = "", tags: str = "", limit: int = 10
    ) -> list[dict]:
        cursor = self.storage.connection.cursor()
        sql = "SELECT id, topic, kind, content, created_at, tags, pinned FROM notes WHERE topic = ?"
        params: list = [self.normalize_topic(topic)]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if query:
            like = f"%{query}%"
            sql += " AND (content LIKE ? OR title LIKE ?)"
            params.extend([like, like])
        if tags:
            for tag in tags.split(","):
                tag = tag.strip()
                if tag:
                    sql += " AND tags LIKE ?"
                    params.append(f"%\"{tag}\"%")
        sql += " ORDER BY pinned DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = cursor.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def pin_note(self, note_id: int | str) -> tuple[bool, str]:
        from .planets import _exec as _pexec

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        _pexec(self.storage.connection, "UPDATE notes SET pinned = 1 WHERE id = ?", (nid,))
        return True, f"Pinned note-{nid}"

    def unpin_note(self, note_id: int | str) -> tuple[bool, str]:
        from .planets import _exec as _pexec

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        _pexec(self.storage.connection, "UPDATE notes SET pinned = 0 WHERE id = ?", (nid,))
        return True, f"Unpinned note-{nid}"

    def tag_note(self, note_id: int | str, tags: list[str]) -> tuple[bool, str]:
        from .planets import _exec as _pexec

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        _pexec(self.storage.connection, "UPDATE notes SET tags = ? WHERE id = ?", (json.dumps(tags), nid))
        return True, f"Tagged note-{nid} with {tags}"

    def search_all(self, query: str, limit: int = 10) -> dict:
        like = f"%{query}%"
        cursor = self.storage.connection.cursor()

        planet_rows = cursor.execute(
            "SELECT topic, display_topic, current_state, goal FROM planets WHERE topic LIKE ? OR display_topic LIKE ? OR current_state LIKE ? OR goal LIKE ?",
            (like, like, like, like),
        ).fetchall()
        planets = [dict(r) for r in planet_rows]

        note_rows = cursor.execute(
            "SELECT id, topic, kind, content, title FROM notes WHERE content LIKE ? OR title LIKE ? LIMIT ?",
            (like, like, limit),
        ).fetchall()
        notes = [dict(r) for r in note_rows]

        return {"planets": planets, "notes": notes}

    def reinforce_link(self, from_note_id: int, to_note_id: int, increment: float = 0.05):
        from .planets import _exec as _pexec

        from_id, to_id = sorted([from_note_id, to_note_id])
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
            (from_id, to_id),
        ).fetchone()
        if row:
            new_weight = round(min(1.0, row["weight"] + increment), 3)
            _pexec(
                self.storage.connection,
                "UPDATE note_links SET weight = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                (new_weight, self._now(), from_id, to_id),
            )

    def recompute_links(self, topic: str | None = None, threshold: float = 0.1, min_weight: float = 0.05) -> dict:
        from .planets import _exec as _pexec

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
                        _pexec(
                            self.storage.connection,
                            "UPDATE note_links SET weight = ?, confidence = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                            (new_weight, confidence, self._now(), from_id, to_id),
                        )
                    else:
                        _pexec(
                            self.storage.connection,
                            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, 'auto', ?, ?, 'auto')",
                            (from_id, to_id, round(score, 3), confidence),
                        )
                        created += 1
                elif existing and score < min_weight:
                    _pexec(
                        self.storage.connection,
                        "DELETE FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                        (from_id, to_id),
                    )
                    removed += 1
        return {"created": created, "removed": removed, "total_pairs": len(notes) * (len(notes) - 1) // 2}

    def get_neighbors_weighted(self, note_id: int, depth: int = 1, min_weight: float = 0.0) -> list[dict]:
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

    def get_subgraph(self, note_id: int, depth: int = 2, min_weight: float = 0.2) -> dict:
        cursor = self.storage.connection.cursor()
        nid = self._parse_note_id(note_id)
        if nid is None:
            return {"nodes": [], "edges": []}
        node_ids = {nid}
        edges: list[dict] = []
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

    def rank_neighbors(self, note_id: int, by: str = "weight") -> list[dict]:
        neighbors = self.get_note_neighbors(note_id)
        if by == "confidence":
            neighbors.sort(key=lambda x: x.get("confidence", 0) or 0, reverse=True)
        else:
            neighbors.sort(key=lambda x: x.get("weight", 0) or 0, reverse=True)
        return neighbors

    def get_notes_for_planet(self, topic: str, limit: int = 50) -> list[dict]:
        slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT ?",
            (slug, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_note_links_for_planet(self, topic: str) -> list[dict]:
        slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            """SELECT from_note_id, to_note_id, link_type, weight, confidence, source
               FROM note_links
               WHERE from_note_id IN (SELECT id FROM notes WHERE topic = ?)
                  OR to_note_id IN (SELECT id FROM notes WHERE topic = ?)""",
            (slug, slug),
        ).fetchall()
        return [dict(r) for r in rows]
