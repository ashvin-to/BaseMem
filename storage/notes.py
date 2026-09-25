"""Note operations — durable facts, decisions, issues stored in notes table."""

from __future__ import annotations

import difflib
import json
import logging
import os
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from storage.db import exec_stmt

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


def fts_escape_token(token: str) -> str:
    """Escape a single token for safe embedding in an FTS5 MATCH expression."""
    return '"' + token.replace('"', '""') + '"'


def fts_or_query(tokens: list[str]) -> str:
    """Build an OR-joined FTS5 MATCH query from raw tokens."""
    return " OR ".join(fts_escape_token(t) for t in tokens)


def tokenize_query(text: str) -> list[str]:
    """Tokenize user prompt text into FTS5-safe search tokens (len>=3, no stopwords)."""
    import re
    words = re.findall(r"[a-zA-Z0-9_]{3,}", (text or "").lower())
    seen: list[str] = []
    for w in words:
        if w in STOPWORDS or w in seen:
            continue
        seen.append(w)
    return seen


class NoteMixin:
    """Mixin providing note CRUD and linking methods. Requires self.storage (StorageManager)."""

    storage: StorageManager
    stamp_note: Any
    _render_sessions_block: Any
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
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)

        kind = kind.lower().strip() or "fact"
        now = self._now()
        exec_stmt(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, title, agent_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (topic_slug, kind, content, title or content[:80], agent_id, status, now, now),
        )
        exec_stmt(
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

        if note_row and hasattr(self, 'get_active_session'):
            session = self.get_active_session(topic_slug, agent_id)
            if session:
                exec_stmt(self.storage.connection, "UPDATE notes SET session_id = ? WHERE id = ?", (session["id"], note_row["id"]))
                self.stamp_note(session["id"], note_row["id"])

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
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
        now = self._now()
        exec_stmt(
            self.storage.connection,
            "INSERT INTO notes (topic, kind, content, agent_id, status, created_at, updated_at) VALUES (?, 'turn', ?, ?, 'open', ?, ?)",
            (topic_slug, content, agent_id, now, now),
        )
        exec_stmt(
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

        from_id = self._parse_note_id(from_note_id)
        to_id = self._parse_note_id(to_note_id)
        if from_id is None or to_id is None:
            return False, "Invalid note ID"
        if from_id == to_id:
            return False, "Cannot link a note to itself"
        from_id, to_id = sorted([from_id, to_id])
        exec_stmt(
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

    def auto_extract_memories(self, topic: str, text: str, agent_id: str = "default") -> list[dict]:
        """Automatically parse text to extract decisions & facts, creating notes in storage."""
        import re

        topic_slug = self.normalize_topic(topic)
        extracted = []

        lines = text.split("\n")
        for line in lines:
            line_str = line.strip()
            if not line_str or len(line_str) < 10:
                continue

            if re.search(
                r"\b(decided|decide|agreed|agree|chose|choose|selected|select|opted|opt|will use|we will|should|must|plan to|decision|decision is|arch)\b",
                line_str,
                re.IGNORECASE,
            ):
                title = line_str[:80]
                note = self.add_note(topic, topic_slug, "decision", line_str, agent_id=agent_id, title=title)
                extracted.append({"type": "decision", "note_id": note["id"], "content": line_str})
            elif re.search(
                r"\b(note|fact|key|config|setting|path|bug|error|issue|fail|failed|failure|broken|crash|regression|root cause|unexpected|doesn.t work|not working)\b",
                line_str,
                re.IGNORECASE,
            ):
                title = line_str[:80]
                note = self.add_note(topic, topic_slug, "fact", line_str, agent_id=agent_id, title=title)
                extracted.append({"type": "fact", "note_id": note["id"], "content": line_str})

        return extracted

    def resolve_contradictions(self, topic: str) -> dict:
        """Scan notes in a topic for contradictions and mark older ones as superseded."""
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            "SELECT id, kind, title, content, created_at, status FROM notes WHERE topic = ? AND status != 'superseded' ORDER BY id ASC",
            (topic_slug,),
        ).fetchall()
        notes = [dict(r) for r in rows]

        resolved = []
        for i in range(len(notes)):
            for j in range(i + 1, len(notes)):
                n1 = notes[i]
                n2 = notes[j]

                tokens1 = self._tokenize(n1["title"] + " " + n1["content"])
                tokens2 = self._tokenize(n2["title"] + " " + n2["content"])

                if not tokens1 or not tokens2:
                    continue

                overlap = len(tokens1 & tokens2)
                if overlap >= 2:
                    t1_text = (n1["title"] + " " + n1["content"]).lower()
                    t2_text = (n2["title"] + " " + n2["content"]).lower()

                    is_conflict = False
                    if ("not" in t1_text and "not" not in t2_text) or ("disable" in t1_text and "enable" in t2_text) or ("false" in t1_text and "true" in t2_text) or ("deprecated" in t2_text or "superseded" in t2_text or "instead of" in t2_text):
                        is_conflict = True

                    if is_conflict:
                        exec_stmt(
                            self.storage.connection,
                            "UPDATE notes SET status = 'superseded' WHERE id = ?",
                            (n1["id"],),
                        )
                        self.link_notes(n1["id"], n2["id"], link_type="contradicts", weight=1.0)
                        resolved.append({
                            "superseded_note_id": f"note-{n1['id']}",
                            "active_note_id": f"note-{n2['id']}",
                            "reason": f"Conflict detected between note-{n1['id']} and note-{n2['id']}",
                        })

        return {"topic": topic_slug, "resolved_count": len(resolved), "conflicts": resolved}

    def _auto_link_note(self, note_id: int, topic_slug: str) -> None:

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
                exec_stmt(
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

    def _get_key_notes(self, topic_slug: str, query: str | None) -> list[dict]:
        cursor = self.storage.connection.cursor()
        key_notes = []
        if query and query.strip():
            # Construct a robust FTS5 query with stop words removed, joined with OR
            import re
            terms = re.findall(r"[\w]+", query)
            stop_words = {
                "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
                "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can't",
                "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
                "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
                "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how",
                "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
                "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
                "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd",
                "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their",
                "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
                "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
                "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's",
                "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd",
                "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
            }
            keywords = [t for t in terms if t.lower() not in stop_words]
            if not keywords:
                keywords = terms
            
            fts_query = " OR ".join(f'"{kw}"*' for kw in keywords) if keywords else ""
            
            if fts_query:
                # First attempt FTS5 search
                try:
                    fts_rows = cursor.execute("""
                        SELECT n.* FROM notes n
                        JOIN notes_fts f ON n.id = f.rowid
                        WHERE f.topic = ? AND n.status NOT IN ('closed', 'resolved')
                          AND (n.kind IS NULL OR LOWER(n.kind) != 'flag')
                          AND n.content NOT LIKE 'missed_%' AND n.content NOT LIKE 'pending_%'
                          AND notes_fts MATCH ?
                        ORDER BY rank
                        LIMIT 4
                    """, (topic_slug, fts_query)).fetchall()
                    key_notes = [dict(r) for r in fts_rows]
                except Exception:
                    key_notes = []
            
            if len(key_notes) < 4:
                exclude_ids = [n["id"] for n in key_notes]
                needed = 4 - len(key_notes)
                placeholders = ",".join("?" for _ in exclude_ids)
                exclude_clause = f"AND id NOT IN ({placeholders})" if exclude_ids else ""
                pad_query = f"""
                    SELECT * FROM notes
                    WHERE topic = ? AND status NOT IN ('closed', 'resolved')
                      AND (kind IS NULL OR LOWER(kind) != 'flag')
                      AND content NOT LIKE 'missed_%' AND content NOT LIKE 'pending_%' {exclude_clause}
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params = [topic_slug] + exclude_ids + [needed]
                try:
                    pad_rows = cursor.execute(pad_query, params).fetchall()
                    key_notes.extend([dict(r) for r in pad_rows])
                except Exception:
                    pass
        else:
            # Fallback to existing behavior: select most recent 4, reverse to get older-first order
            try:
                rows = cursor.execute("""
                    SELECT * FROM notes
                    WHERE topic = ? AND status NOT IN ('closed', 'resolved')
                      AND (kind IS NULL OR LOWER(kind) != 'flag')
                      AND content NOT LIKE 'missed_%' AND content NOT LIKE 'pending_%'
                    ORDER BY created_at DESC
                    LIMIT 4
                """, (topic_slug,)).fetchall()
                key_notes = [dict(r) for r in reversed(rows)]
            except Exception:
                pass
        return key_notes

    def _injected_notes_dir(self) -> str:
        """Directory for the per-topic injected-notes dedup cache.

        Honors BASEMEM_INJECTED_DIR (test override), else ~/.basemem/injected-notes.
        """
        override = os.environ.get("BASEMEM_INJECTED_DIR")
        if override:
            return override
        return os.path.join(os.path.expanduser("~"), ".basemem", "injected-notes")

    def _write_injected_notes_cache(self, topic_slug: str, note_ids: list[int]) -> None:
        """Best-effort; never raises. Powers dedup in `mem prompt-context`."""
        try:
            d = self._injected_notes_dir()
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{topic_slug}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"note_ids": note_ids, "written_at": self._now()}, f)
        except Exception:
            pass

    def build_agent_context(
        self, topic: str, query: str | None = None, result_limit: int = 5
    ) -> str:
        from .planets import _get_planet

        topic_slug = self.normalize_topic(topic)
        proxy = _get_planet(self.storage.connection, topic_slug)
        if not proxy:
            cwd = os.getcwd()
            return (
                "# New Project — No Memory Found\n"
                f"Topic: {topic}\n"
                "Status: not tracked\n"
                "\n"
                "No memory exists for this project yet. BaseMem has noted the project name.\n"
                "Suggested first actions:\n"
                f"1. Call update_planet(topic='{topic}', goal='<one sentence goal>', currentState='<what you observe now>')\n"
                "   to create a planet and start tracking decisions for this project.\n"
                f"2. Call code_init(projectRoot='{cwd}') to index the codebase so code_find\n"
                "   and get_review_context work correctly (takes 1-10 seconds depending on size).\n"
                f"3. After any decision or change, call logInteraction(topic='{topic}', decision='full sentence').\n"
                "\n"
                "Once a planet exists, future sessions will inject memory context automatically."
            )

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

        lines.extend([
            "",
            "## Code Intelligence",
            "Use code_find/code_read/code_explore/code_files (MCP) instead of grep/glob/read. "
            "Auto-index on first use; for plain text search use code_find(query, grep=True); "
            "empty results → code_init first. Review blast-radius: get_review_context(files).",
        ])

        next_steps = list(metadata.get("next_steps", []))[::-1]
        single_step = metadata.get("next_step", "")
        if single_step:
            if single_step in next_steps:
                next_steps.remove(single_step)
            next_steps.insert(0, single_step)
        if next_steps:
            lines.extend([
                "",
                "## Next Steps",
                *[f"- {self._trim_text(step, 180)}" for step in next_steps[:3]],
            ])

        all_notes = metadata.get("notes", [])
        pinned_notes = [n for n in all_notes if n.get("pinned")]
        if pinned_notes:
            lines.extend([
                "",
                "## Pinned Notes",
                *[
                    f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 300)}"
                    for n in pinned_notes
                ],
            ])

        session_lines = self._render_sessions_block(topic_slug)
        if session_lines:
            lines.extend([
                "",
                "## Sessions",
                *session_lines,
            ])

        key_notes = self._get_key_notes(topic_slug, query)
        if key_notes:
            lines.extend([
                "",
                "## Key Notes",
                *[
                    f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 300)}"
                    for n in key_notes
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
                        f"- [{node.node_type.value}] {node.title}: {self._trim_text(node.content, 300)}"
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

        # Record which notes were just surfaced so `mem prompt-context` can dedup
        # them (avoid re-injecting the same note on the first per-prompt recall).
        try:
            injected_ids = [
                n["id"] for n in (pinned_notes + key_notes) if isinstance(n.get("id"), int)
            ]
            injected_ids = list(dict.fromkeys(injected_ids))
            if injected_ids:
                self._write_injected_notes_cache(topic_slug, injected_ids)
        except Exception:
            pass

        return "\n".join(lines)

    def get_note(self, note_id: int) -> dict | None:
        cursor = self.storage.connection.cursor()
        row = cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    def search_notes_fts(
        self,
        topic: str,
        query: str,
        limit: int = 10,
        exclude_ids: set[int] | None = None,
    ) -> list[dict]:
        """FTS5 search over notes_fts scoped to a topic. Returns ranked note dicts.

        Used by the per-prompt recall hook (`mem prompt-context`): the user
        prompt is tokenized into an OR query so any matching token hits.
        Falls back to per-token LIKE search when FTS5 is unavailable.

        exclude_ids: optional set of note ids to suppress (dedup against notes
        already surfaced by `mem agent-context`). Applied to both the FTS path
        and the LIKE fallback.
        """
        slug = self.normalize_topic(topic)
        tokens = tokenize_query(query)
        if not tokens:
            return []
        exclude_ids = exclude_ids or set()
        exclude_list = sorted(int(i) for i in exclude_ids if isinstance(i, int))
        fts_query = fts_or_query(tokens)
        cursor = self.storage.connection.cursor()
        exclude_clause = ""
        excl_params: list = []
        if exclude_list:
            ph = ",".join("?" for _ in exclude_list)
            exclude_clause = f" AND n.id NOT IN ({ph})"
            excl_params = list(exclude_list)
        try:
            rows = cursor.execute(
                """SELECT n.id, n.topic, n.kind, n.content, n.title, n.created_at, n.tags, n.pinned
                   FROM notes n
                   JOIN notes_fts f ON n.id = f.rowid
                   WHERE f.topic = ? AND notes_fts MATCH ?""" + exclude_clause + """
                   ORDER BY rank LIMIT ?""",
                [slug, fts_query] + excl_params + [limit],
            ).fetchall()
            hits = [dict(r) for r in rows]
            if hits:
                return hits
        except Exception as e:
            logger.debug(f"search_notes_fts FTS failed, falling back to LIKE: {e}")
        # Fallback: per-token LIKE union (same semantics, no ranking)
        seen: set = set()
        out: list[dict] = []
        for tok in tokens[:12]:
            like = f"%{tok}%"
            try:
                rows = cursor.execute(
                    """SELECT id, topic, kind, content, title, created_at, tags, pinned FROM notes
                       WHERE topic = ? AND (content LIKE ? OR title LIKE ?)
                       ORDER BY pinned DESC, created_at DESC LIMIT ?""",
                    (slug, like, like, limit),
                ).fetchall()
            except Exception:
                continue
            for r in rows:
                d = dict(r)
                if exclude_list and d.get("id") in exclude_list:
                    continue
                if d.get("id") not in seen:
                    seen.add(d.get("id"))
                    out.append(d)
            if len(out) >= limit:
                break
        return out[:limit]

    def list_notes(
        self, topic: str = "", kind: str = "", limit: int = 10, pinned_only: bool = False
    ) -> list[dict]:
        """List notes, newest first. Empty topic = all planets."""
        cursor = self.storage.connection.cursor()
        sql = "SELECT id, topic, kind, title, content, created_at, tags, pinned FROM notes"
        cond: list[str] = []
        params: list = []
        if topic:
            cond.append("topic = ?")
            params.append(self.normalize_topic(topic))
        if kind:
            cond.append("kind = ?")
            params.append(kind)
        if pinned_only:
            cond.append("pinned = 1")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = cursor.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_notes(
        self, topic: str, kind: str = "", query: str = "", tags: str = "", limit: int = 10
    ) -> list[dict]:
        cursor = self.storage.connection.cursor()
        sql = "SELECT id, topic, kind, content, created_at, tags, pinned FROM notes"
        params: list = []
        where_added = False
        if topic:
            sql += " WHERE topic = ?"
            params.append(self.normalize_topic(topic))
            where_added = True
        if kind:
            sql += (" AND " if where_added else " WHERE ") + "kind = ?"
            where_added = True
            params.append(kind)
        if query:
            like = f"%{query}%"
            sql += (" AND " if where_added else " WHERE ") + "(content LIKE ? OR title LIKE ?)"
            where_added = True
            params.extend([like, like])
        if tags:
            for tag in tags.split(","):
                tag = tag.strip()
                if tag:
                    sql += (" AND " if where_added else " WHERE ") + "tags LIKE ?"
                    where_added = True
                    params.append(f"%\"{tag}\"%")
        sql += " ORDER BY pinned DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = cursor.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def pin_note(self, note_id: int | str) -> tuple[bool, str]:

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        exec_stmt(self.storage.connection, "UPDATE notes SET pinned = 1 WHERE id = ?", (nid,))
        return True, f"Pinned note-{nid}"

    def unpin_note(self, note_id: int | str) -> tuple[bool, str]:

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        exec_stmt(self.storage.connection, "UPDATE notes SET pinned = 0 WHERE id = ?", (nid,))
        return True, f"Unpinned note-{nid}"

    def tag_note(self, note_id: int | str, tags: list[str]) -> tuple[bool, str]:

        nid = self._parse_note_id(note_id)
        if nid is None:
            return False, "Invalid note ID"
        row = self.get_note(nid)
        if not row:
            return False, f"Note not found: {note_id}"
        exec_stmt(self.storage.connection, "UPDATE notes SET tags = ? WHERE id = ?", (json.dumps(tags), nid))
        return True, f"Tagged note-{nid} with {tags}"

    def note_update(self, note_id: int | str, pinned: bool | None = None, tags: str | None = None) -> str:
        """Update a note's pinned status and/or tags. At least one of pinned or tags must be provided."""
        if pinned is None and tags is None:
            return "Error: at least one of pinned or tags must be provided."
        parts = []
        if pinned is not None:
            if pinned:
                ok, msg = self.pin_note(note_id)
            else:
                ok, msg = self.unpin_note(note_id)
            parts.append(msg)
        if tags is not None:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            ok, msg = self.tag_note(note_id, tag_list)
            parts.append(msg)
        return " | ".join(parts)

    def search_all(self, query: str, limit: int = 10) -> dict:
        terms = [t for t in query.lower().split() if len(t) > 1] or [query.lower()]
        term_params = [f"%{term}%" for term in terms]

        def field_match(field: str) -> str:
            return " OR ".join([f"LOWER({field}) LIKE ?" for _ in terms])

        cursor = self.storage.connection.cursor()

        planet_rows = cursor.execute(
            "SELECT topic, display_topic, current_state, goal FROM planets WHERE "
            + " OR ".join(field_match(field) for field in ("topic", "display_topic", "current_state", "goal")),
            term_params * 4,
        ).fetchall()
        planets = [dict(r) for r in planet_rows]

        note_rows = cursor.execute(
            "SELECT id, topic, kind, content, title FROM notes WHERE "
            + " OR ".join(field_match(field) for field in ("content", "title"))
            + " LIMIT ?",
            term_params * 2 + [limit],
        ).fetchall()
        notes = [dict(r) for r in note_rows]

        return {"planets": planets, "notes": notes}

    def reinforce_link(self, from_note_id: int, to_note_id: int, increment: float = 0.05):

        from_id, to_id = sorted([from_note_id, to_note_id])
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
            (from_id, to_id),
        ).fetchone()
        if row:
            new_weight = round(min(1.0, row["weight"] + increment), 3)
            exec_stmt(
                self.storage.connection,
                "UPDATE note_links SET weight = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                (new_weight, self._now(), from_id, to_id),
            )

    def recompute_links(self, topic: str | None = None, threshold: float = 0.1, min_weight: float = 0.05) -> dict:

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
                        exec_stmt(
                            self.storage.connection,
                            "UPDATE note_links SET weight = ?, confidence = ?, updated_at = ? WHERE from_note_id = ? AND to_note_id = ? AND link_type = 'auto'",
                            (new_weight, confidence, self._now(), from_id, to_id),
                        )
                    else:
                        exec_stmt(
                            self.storage.connection,
                            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source) VALUES (?, ?, 'auto', ?, ?, 'auto')",
                            (from_id, to_id, round(score, 3), confidence),
                        )
                        created += 1
                elif existing and score < min_weight:
                    exec_stmt(
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

    def rank_context(
        self,
        topic: str,
        query: str = "",
        limit: int = 20,
        w_fts: float = 0.4,
        w_graph: float = 0.4,
        w_recency: float = 0.2,
    ) -> list[dict]:
        """Multi-layer context re-ranking combining FTS similarity, graph distance/weight, and recency."""
        slug = self.normalize_topic(topic)
        notes = self.get_notes_for_planet(slug, limit=100)
        if not notes:
            return []

        query_tokens = self._tokenize(query) if query else set()
        max_id = max(n["id"] for n in notes) if notes else 1

        results = []
        for n in notes:
            nid = n["id"]
            title_text = n.get("title") or ""
            content_text = n.get("content") or ""

            if query_tokens:
                note_tokens = self._tokenize(title_text + " " + content_text)
                overlap = len(query_tokens & note_tokens) if note_tokens else 0
                fts_score = overlap / len(query_tokens)
            else:
                fts_score = 0.5

            neighbors = self.get_note_neighbors(nid)
            if neighbors:
                avg_weight = sum(nb.get("weight", 1.0) for nb in neighbors) / len(neighbors)
                graph_score = min(1.0, (len(neighbors) * 0.2) + (avg_weight * 0.4))
            else:
                graph_score = 0.1

            recency_score = nid / max_id if max_id > 0 else 1.0
            final_score = (w_fts * fts_score) + (w_graph * graph_score) + (w_recency * recency_score)

            note_dict = dict(n)
            note_dict["score"] = round(final_score, 4)
            note_dict["fts_score"] = round(fts_score, 4)
            note_dict["graph_score"] = round(graph_score, 4)
            note_dict["recency_score"] = round(recency_score, 4)
            results.append(note_dict)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
