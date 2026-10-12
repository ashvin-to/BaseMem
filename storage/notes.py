"""Note operations — durable facts, decisions, issues stored in notes table."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from typing import TYPE_CHECKING, Any

from storage.db import exec_stmt
from storage.extraction import HeuristicExtractor, MemoryExtractor

if TYPE_CHECKING:
    from storage.db import StorageManager

logger = logging.getLogger(__name__)


class NoteRelation(str, Enum):
    RELATED_TO = "related_to"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    REFERENCES = "references"
    MENTIONS = "mentions"
    REFERENCES_CODE = "references_code"
    AFFECTS_CODE = "affects_code"
    DEFINED_IN = "defined_in"


RELATED_TO = NoteRelation.RELATED_TO.value
SUPERSEDES = NoteRelation.SUPERSEDES.value
SUPERSEDED_BY = NoteRelation.SUPERSEDED_BY.value
CONTRADICTS = NoteRelation.CONTRADICTS.value
SUPPORTS = NoteRelation.SUPPORTS.value
DEPENDS_ON = NoteRelation.DEPENDS_ON.value
DERIVED_FROM = NoteRelation.DERIVED_FROM.value
REFERENCES = NoteRelation.REFERENCES.value
MENTIONS = NoteRelation.MENTIONS.value
REFERENCES_CODE = NoteRelation.REFERENCES_CODE.value
AFFECTS_CODE = NoteRelation.AFFECTS_CODE.value
DEFINED_IN = NoteRelation.DEFINED_IN.value


@dataclass(frozen=True)
class NoteLink:
    from_note_id: int
    to_note_id: int
    relation: str
    weight: float = 1.0
    confidence: float = 1.0
    source: str = "explicit"
    provenance: dict | str = ""
    created_at: str | None = None
    updated_at: str | None = None

    RELATED_TO = RELATED_TO
    SUPERSEDES = SUPERSEDES
    SUPERSEDED_BY = SUPERSEDED_BY
    CONTRADICTS = CONTRADICTS
    SUPPORTS = SUPPORTS
    DEPENDS_ON = DEPENDS_ON
    DERIVED_FROM = DERIVED_FROM
    REFERENCES = REFERENCES
    MENTIONS = MENTIONS
    REFERENCES_CODE = REFERENCES_CODE
    AFFECTS_CODE = AFFECTS_CODE
    DEFINED_IN = DEFINED_IN

    @classmethod
    def from_row(cls, row: Any) -> NoteLink:
        values = dict(row)
        return cls(
            from_note_id=values["from_note_id"],
            to_note_id=values["to_note_id"],
            relation=str(values.get("link_type", values.get("relation")) or RELATED_TO),
            weight=float(values.get("weight") or 0.0),
            confidence=float(values.get("confidence") or 0.0),
            source=values.get("source") or "explicit",
            provenance=values.get("provenance") or "",
            created_at=values.get("created_at"),
            updated_at=values.get("updated_at"),
        )


STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "need",
    "dare",
    "ought",
    "used",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "because",
    "but",
    "and",
    "or",
    "if",
    "while",
    "that",
    "this",
    "it",
    "its",
    "you",
    "your",
    "we",
    "our",
    "they",
    "them",
    "their",
    "i",
    "me",
    "my",
    "he",
    "him",
    "his",
    "she",
    "her",
    "who",
    "whom",
    "which",
    "what",
    "about",
    "up",
    "down",
    "let",
    "get",
    "got",
    "also",
    "make",
    "made",
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
    get_or_create_planet: Any
    memory_extractor: MemoryExtractor

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

    NOTE_TYPES = frozenset(
        {
            "FACT",
            "DECISION",
            "CONSTRAINT",
            "PREFERENCE",
            "DISCOVERY",
            "BUG",
            "WORKAROUND",
            "ARCHITECTURE",
            "CONVENTION",
            "HYPOTHESIS",
            "HISTORY",
            "SUMMARY",
            "TURN",
            "ISSUE",
            "QUESTION",
            "TASK_ARCHIVE",
        }
    )
    NOTE_RELATIONSHIPS = frozenset(item.value for item in NoteRelation) | {"related"}
    AUTO_LINK_MIN_CONFIDENCE = 0.3

    def create_note(self, topic: str, kind: str, content: str, **metadata: Any) -> dict:
        normalized = kind.upper().strip()
        if normalized not in self.NOTE_TYPES:
            raise ValueError(f"unsupported note type: {kind}")
        return self.add_note(
            "",
            topic,
            normalized,
            content,
            **{
                k: v
                for k, v in metadata.items()
                if k
                in {
                    "agent_id",
                    "title",
                    "status",
                    "source_path",
                    "artifact_path",
                    "observed_at",
                    "verification_status",
                    "evidence_summary",
                    "importance",
                    "confidence",
                    "scope",
                    "source",
                    "provenance",
                    "valid_from",
                    "valid_until",
                }
            },
        )

    def list_notes(
        self, topic: str = "", kind: str = "", status: str | None = None, include_superseded: bool = False, limit: int = 100, pinned_only: bool = False
    ) -> list[dict]:
        where, params = [], []
        if topic:
            where.append("topic = ?")
            params.append(self.normalize_topic(topic))
        if kind:
            where.append("UPPER(kind) = ?")
            params.append(kind.upper())
        if status:
            where.append("status = ?")
            params.append(status)
        if pinned_only:
            where.append("pinned = 1")
        if not include_superseded:
            where.append("COALESCE(status, 'open') != 'superseded'")
        sql = "SELECT * FROM notes" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY importance DESC, pinned DESC, updated_at DESC LIMIT ?"
        return [dict(r) for r in self.storage.connection.execute(sql, (*params, limit)).fetchall()]

    def update_note(self, note_id: int | str, **fields: Any) -> dict:
        nid = self._parse_note_id(note_id)
        if nid is None:
            raise ValueError("invalid note id")
        allowed = {
            "content",
            "title",
            "kind",
            "status",
            "scope",
            "source",
            "importance",
            "confidence",
            "valid_from",
            "valid_until",
            "supersedes",
            "superseded_by",
            "updated_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "kind" in updates:
            updates["kind"] = str(updates["kind"]).upper()
        updates.setdefault("updated_at", self._now())
        clause = ", ".join(f"{k}=?" for k in updates)
        self.storage.connection.execute(f"UPDATE notes SET {clause} WHERE id=?", (*updates.values(), nid))
        self.storage.connection.commit()
        return dict(self.storage.connection.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone())

    def delete_note(self, note_id: int | str) -> bool:
        nid = self._parse_note_id(note_id)
        if nid is None:
            return False
        self.storage.connection.execute("DELETE FROM notes WHERE id=?", (nid,))
        self.storage.connection.commit()
        return True

    def get_note(self, note_id: int | str) -> dict | None:
        nid = self._parse_note_id(note_id)
        row = self.storage.connection.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone() if nid is not None else None
        return dict(row) if row else None

    def add_note(
        self,
        _folder_name: str,
        topic: str,
        kind: str,
        content: str,
        agent_id: str = "default",
        title: str | None = None,
        status: str = "open",
        source_path: str = "",
        artifact_path: str = "",
        observed_at: str = "",
        verification_status: str = "memory_only",
        evidence_summary: str = "",
        importance: float = 0.5,
        confidence: float = 0.5,
        scope: str = "",
        source: str = "",
        provenance: dict | str = "",
        valid_from: str = "",
        valid_until: str = "",
    ) -> dict:
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_planet(topic, topic)

        kind = kind.lower().strip() or "fact"
        now = self._now()
        exec_stmt(
            self.storage.connection,
            "INSERT INTO notes "
            "(topic, kind, content, title, agent_id, status, source_path, artifact_path, "
            "observed_at, verification_status, evidence_summary, importance, confidence, scope, source, provenance, "
            "valid_from, valid_until, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                topic_slug,
                kind,
                content,
                title or content[:80],
                agent_id,
                status,
                source_path,
                artifact_path,
                observed_at,
                verification_status,
                evidence_summary,
                max(0.0, min(1.0, float(importance))),
                max(0.0, min(1.0, float(confidence))),
                scope,
                source,
                provenance if isinstance(provenance, str) else json.dumps(provenance),
                valid_from or now,
                valid_until or None,
                now,
                now,
            ),
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

        if note_row and hasattr(self, "get_active_session"):
            session = self.get_active_session(topic_slug, agent_id)
            if session:
                exec_stmt(self.storage.connection, "UPDATE notes SET session_id = ? WHERE id = ?", (session["id"], note_row["id"]))
                self.stamp_note(session["id"], note_row["id"])

        count = self.get_note_count(topic)
        result = {"id": note_id, "title": title or content[:80], "content": content}
        if count >= self.SUMMARIZE_THRESHOLD:
            result["_suggest"] = f"This planet has {count} notes. Consider summarizing via `kb planet summarize {topic}` or the summarize_planet MCP tool."
        return result

    def link_symbol_refs(self, note_id: str, topic: str, refs: list, project_root: str = "") -> int:
        """Attach code symbols to a memory note.

        `refs` is a list of (file_path, symbol_name, content_hash) tuples. The
        content_hash is what lets a link survive a rename: if the body is unchanged
        at a new path, notes_for_symbol still finds it.
        """
        if not note_id or not note_id.startswith("note-"):
            return 0
        try:
            numeric = int(note_id.split("-", 1)[1])
        except (ValueError, IndexError):
            return 0
        topic_slug = self.normalize_topic(topic)
        linked = 0
        for file_path, symbol_name, content_hash in refs:
            if not file_path:
                continue
            exec_stmt(
                self.storage.connection,
                "INSERT OR IGNORE INTO code_symbol_refs "
                "(note_id, topic, file_path, symbol_name, content_hash, project_root) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (numeric, topic_slug, file_path, symbol_name or "", content_hash or "", project_root or ""),
            )
            linked += 1
        return linked

    def notes_for_symbol(self, file_path: str = "", symbol_name: str = "", topic: str = "", content_hash: str = "") -> list[dict]:
        """Memory notes referencing a symbol, a file, or a content hash."""
        where, params = [], []
        if file_path:
            where.append("r.file_path = ?")
            params.append(file_path)
        if symbol_name:
            where.append("r.symbol_name = ?")
            params.append(symbol_name)
        if content_hash:
            where.append("r.content_hash = ?")
            params.append(content_hash)
        if topic:
            where.append("r.topic = ?")
            params.append(self.normalize_topic(topic))
        if not where:
            return []
        sql = (
            "SELECT r.note_id, r.file_path, r.symbol_name, r.created_at, "
            "n.kind, n.title, substr(n.content, 1, 400) AS content, n.topic "
            "FROM code_symbol_refs r LEFT JOIN notes n ON n.id = r.note_id "
            f"WHERE {' AND '.join(where)} ORDER BY r.created_at DESC LIMIT 100"
        )
        rows = self.storage.connection.cursor().execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def symbol_refs_for_note(self, note_id: str) -> list[dict]:
        try:
            numeric = int(note_id.split("-", 1)[1])
        except (ValueError, IndexError):
            return []
        rows = self.storage.connection.cursor().execute(
            "SELECT file_path, symbol_name, content_hash, created_at FROM code_symbol_refs "
            "WHERE note_id = ? ORDER BY file_path",
            (numeric,),
        ).fetchall()
        return [dict(r) for r in rows]

    def unlink_symbol_ref(self, note_id: str, file_path: str, symbol_name: str = "") -> int:
        try:
            numeric = int(note_id.split("-", 1)[1])
        except (ValueError, IndexError):
            return 0
        if symbol_name:
            sql = "DELETE FROM code_symbol_refs WHERE note_id = ? AND file_path = ? AND symbol_name = ?"
            params = (numeric, file_path, symbol_name)
        else:
            sql = "DELETE FROM code_symbol_refs WHERE note_id = ? AND file_path = ?"
            params = (numeric, file_path)
        return exec_stmt(self.storage.connection, sql, params)

    def log_chat_to_planet(self, _folder_name: str, topic: str, content: str, agent_id: str, _sender: str = "ai") -> str | None:
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_planet(topic, topic)
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
            hint = f"This planet has {count} notes. Consider summarizing via `kb planet summarize {topic}` or the summarize_planet MCP tool."
            logger.warning(hint)
            return hint
        return None

    def link_notes(
        self,
        from_note_id: int | str,
        to_note_id: int | str,
        link_type: str = "related",
        weight: float = 1.0,
        provenance: dict | str = "",
        confidence: float = 1.0,
        created_at: str | None = None,
    ) -> tuple[bool, str]:
        from_id = self._parse_note_id(from_note_id)
        to_id = self._parse_note_id(to_note_id)
        if from_id is None or to_id is None:
            return False, "Invalid note ID"
        if from_id == to_id:
            return False, "Cannot link a note to itself"
        relation = link_type.value if isinstance(link_type, NoteRelation) else str(link_type).strip().lower()
        relation = {"related": RELATED_TO, "auto": "lexical_related"}.get(relation, relation)
        if relation not in self.NOTE_RELATIONSHIPS and relation != "lexical_related":
            return False, f"Unsupported relationship: {link_type}"
        timestamp = created_at or self._now()
        link = NoteLink(
            from_id, to_id, relation, max(0.0, min(1.0, float(weight))), max(0.0, min(1.0, float(confidence))), "explicit", provenance, timestamp, timestamp
        )
        exec_stmt(
            self.storage.connection,
            """INSERT OR IGNORE INTO note_links
               (from_note_id, to_note_id, link_type, weight, confidence, source, provenance, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'explicit', ?, ?, ?)""",
            (
                link.from_note_id,
                link.to_note_id,
                link.relation,
                link.weight,
                link.confidence,
                link.provenance if isinstance(link.provenance, str) else json.dumps(link.provenance),
                link.created_at,
                link.updated_at,
            ),
        )
        return True, f"Linked note-{from_id} -> note-{to_id} ({link.relation})"

    def get_note_neighbors(self, note_id: int | str, link_type: str | None = None, direction: str = "both") -> list[dict]:
        nid = self._parse_note_id(note_id)
        if nid is None or direction not in {"out", "in", "both"}:
            return []
        cursor = self.storage.connection.cursor()
        condition = {"out": "nl.from_note_id = ?", "in": "nl.to_note_id = ?", "both": "(nl.from_note_id = ? OR nl.to_note_id = ?)"}[direction]
        params: list[int | str] = [nid] * (2 if direction == "both" else 1)
        where = f"WHERE {condition} AND n.id != ?"
        params.append(nid)
        if link_type:
            where += " AND nl.link_type = ?"
            params.append(link_type.value if isinstance(link_type, NoteRelation) else str(link_type).strip().lower())
        rows = cursor.execute(
            f"""SELECT n.id, n.topic, n.kind, n.content, n.title,
                       nl.link_type AS relation, nl.link_type, nl.from_note_id, nl.to_note_id,
                       nl.weight, nl.confidence, nl.source, nl.provenance, nl.created_at
                FROM notes n JOIN note_links nl ON nl.from_note_id = n.id OR nl.to_note_id = n.id
                {where}""",
            params,
        ).fetchall()
        result = [dict(r) for r in rows]
        for nb in result:
            nb["direction"] = "out" if nb["from_note_id"] == nid else "in"
            if nb.get("source") == "auto" and nb.get("link_type") in {"auto", "lexical_related"}:
                self.reinforce_link(min(nid, nb["id"]), max(nid, nb["id"]))
        return result

    @staticmethod
    def classify_memory_metadata(text: str, agent_id: str = "default") -> dict:
        return HeuristicExtractor._classify((text or "").strip(), agent_id)

    @staticmethod
    def _dedup_status(content: str, existing_notes: list[dict]) -> tuple[str, str | None, float]:
        normalized = re.sub(r"[^\w]+", " ", content.lower()).strip()
        existing = [
            (
                note,
                re.sub(r"[^\w]+", " ", note["content"].lower()).strip(),
            )
            for note in existing_notes
        ]
        for note, candidate in existing:
            if normalized == candidate:
                return "exact_duplicate", note["id"], 1.0

        best_note, best_similarity = None, 0.0
        for note, candidate in existing:
            similarity = SequenceMatcher(None, normalized, candidate).ratio()
            if similarity > best_similarity:
                best_note, best_similarity = note, similarity

        if best_note is not None and best_similarity >= 0.55:
            existing_text = best_note["content"].lower()
            if re.search(r"\b(updated?|changed?|switch(?:ed)?|now|instead of)\b", content.lower()):
                return "updated_version", best_note["id"], best_similarity
            negative_pattern = r"\b(not|never|no|disable|disabled|false|forbidden)\b|n't\b"
            negative_candidate = re.search(negative_pattern, content.lower())
            negative_existing = re.search(negative_pattern, existing_text)
            if bool(negative_candidate) != bool(negative_existing):
                return "contradiction", best_note["id"], best_similarity
        if best_note is not None and best_similarity >= 0.78:
            return "near_duplicate", best_note["id"], best_similarity
        return "independent", None, best_similarity

    def auto_extract_memories(self, topic: str, text: str, agent_id: str = "default") -> list[dict]:
        """Extract memories through the configured extractor and insert new candidates safely."""
        topic_slug = self.normalize_topic(topic)
        extracted = []
        rows = self.storage.connection.execute(
            "SELECT id, content, kind, status, provenance FROM notes WHERE topic = ? ORDER BY id",
            (topic_slug,),
        ).fetchall()
        existing_notes = [dict(row) for row in rows]

        for memory in self.memory_extractor.extract(text, agent_id):
            dedup_status, matched_note_id, similarity = self._dedup_status(memory.content, existing_notes)
            provenance = dict(memory.provenance)
            provenance["dedup"] = {
                "status": dedup_status,
                "similarity": round(similarity, 4),
                "matched_note_id": matched_note_id,
            }
            if dedup_status == "exact_duplicate":
                duplicate_note_id = matched_note_id if str(matched_note_id).startswith("note-") else f"note-{matched_note_id}"
                extracted.append(
                    {
                        "type": memory.type,
                        "note_id": duplicate_note_id,
                        "content": memory.content,
                        "dedup_status": dedup_status,
                        "provenance": provenance,
                    }
                )
                continue
            note = self.add_note(
                topic,
                topic_slug,
                memory.kind,
                memory.content,
                agent_id=agent_id,
                title=memory.content[:80],
                importance=memory.importance,
                confidence=memory.confidence,
                source=memory.source,
                provenance=provenance,
            )
            existing_notes.append({"id": note["id"], "content": memory.content, "kind": memory.kind, "status": "open", "provenance": ""})
            extracted.append(
                {
                    "type": memory.type,
                    "note_id": note["id"],
                    "content": memory.content,
                    "dedup_status": dedup_status,
                    "provenance": provenance,
                }
            )
        return extracted

    def find_contradiction_candidates(self, topic: str) -> list[dict]:
        rows = self.storage.connection.execute(
            "SELECT id, kind, title, content, scope, status FROM notes WHERE topic=? AND COALESCE(status,'open')!='superseded' ORDER BY id",
            (self.normalize_topic(topic),),
        ).fetchall()
        candidates = []
        for i, left in enumerate(rows):
            lt = self._tokenize(left["content"] + " " + left["title"])
            for right in rows[i + 1 :]:
                rt = self._tokenize(right["content"] + " " + right["title"])
                if len(lt & rt) < 2 or (left["scope"] and right["scope"] and left["scope"] != right["scope"]):
                    continue
                if ("not" in left["content"].lower()) != ("not" in right["content"].lower()) or ("disable" in left["content"].lower()) != (
                    "disable" in right["content"].lower()
                ):
                    candidates.append({"older_note_id": left["id"], "candidate_note_id": right["id"], "reason": "negation_or_enablement"})
        return candidates

    def resolve_contradictions(self, topic: str) -> dict:
        """Scan notes in a topic for contradictions and mark older ones as superseded."""
        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        rows = cursor.execute(
            "SELECT id, kind, title, content, created_at, status, scope, valid_from, valid_until FROM notes "
            "WHERE topic = ? AND status != 'superseded' ORDER BY id ASC",
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
                if overlap >= 2 and (not n1.get("scope") or not n2.get("scope") or n1.get("scope") == n2.get("scope")):
                    t1_text = (n1["title"] + " " + n1["content"]).lower()
                    t2_text = (n2["title"] + " " + n2["content"]).lower()

                    is_conflict = False
                    if (
                        ("not" in t1_text and "not" not in t2_text)
                        or ("disable" in t1_text and "enable" in t2_text)
                        or ("false" in t1_text and "true" in t2_text)
                        or ("deprecated" in t2_text or "superseded" in t2_text or "instead of" in t2_text)
                    ):
                        is_conflict = True

                    if is_conflict:
                        exec_stmt(
                            self.storage.connection,
                            "UPDATE notes SET status = 'superseded', superseded_by = ? WHERE id = ?",
                            (n2["id"], n1["id"]),
                        )
                        self.link_notes(n1["id"], n2["id"], link_type="contradicts", weight=1.0)
                        resolved.append(
                            {
                                "superseded_note_id": f"note-{n1['id']}",
                                "active_note_id": f"note-{n2['id']}",
                                "reason": f"Conflict detected between note-{n1['id']} and note-{n2['id']}",
                            }
                        )

        return {"topic": topic_slug, "resolved_count": len(resolved), "conflicts": resolved}

    def _auto_link_note(self, note_id: int, topic_slug: str) -> None:
        cursor = self.storage.connection.cursor()
        new_row = cursor.execute(
            "SELECT id, topic, content, scope, source_path FROM notes WHERE id = ? AND topic = ?",
            (note_id, topic_slug),
        ).fetchone()
        if not new_row:
            return
        new_words = self._tokenize(new_row["content"])
        if len(new_words) < 3:
            return
        new_entity = new_row["source_path"] or new_row["scope"] or ""
        existing = cursor.execute(
            "SELECT id, topic, content, scope, source_path FROM notes WHERE topic = ? AND id != ?",
            (topic_slug, note_id),
        ).fetchall()
        for row in existing:
            existing_entity = row["source_path"] or row["scope"] or ""
            if new_row["scope"] and row["scope"] and new_row["scope"] != row["scope"]:
                continue
            if new_entity and existing_entity and new_entity != existing_entity:
                continue
            existing_words = self._tokenize(row["content"])
            if len(existing_words) < 3:
                continue
            union = new_words | existing_words
            lexical_score = len(new_words & existing_words) / len(union) if union else 0
            confidence = round(min(1.0, lexical_score * 1.5), 3)
            if lexical_score >= 0.2 and confidence >= self.AUTO_LINK_MIN_CONFIDENCE:
                provenance = {"method": "lexical_similarity", "semantic": False, "score": round(lexical_score, 3)}
                exec_stmt(
                    self.storage.connection,
                    """INSERT OR IGNORE INTO note_links
                       (from_note_id, to_note_id, link_type, weight, confidence, source, provenance, created_at, updated_at)
                       VALUES (?, ?, 'lexical_related', ?, ?, 'auto', ?, ?, ?)""",
                    (note_id, row["id"], round(lexical_score, 3), confidence, json.dumps(provenance), self._now(), self._now()),
                )

    def get_note_count(self, topic: str) -> int:

        topic_slug = self.normalize_topic(topic)
        cursor = self.storage.connection.cursor()
        row = cursor.execute("SELECT COUNT(*) AS cnt FROM notes WHERE topic = ?", (topic_slug,)).fetchone()
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

        lines.extend(
            [
                "",
                "--- END OF NOTES ---",
                "",
                "Write a comprehensive summary of this planet as a single note with kind='summary'.",
                "Cover: goal progress, key decisions, open issues, and next steps.",
                "Call add_note(topic, 'summary', '<your summary>') to save it.",
                "After saving, call compact_planet(topic) to trim old notes.",
            ]
        )

        return "\n".join(lines)

    def _get_key_notes(self, topic_slug: str, query: str | None) -> list[dict]:
        cursor = self.storage.connection.cursor()
        key_notes = []
        if query and query.strip():
            # Construct a robust FTS5 query with stop words removed, joined with OR
            import re

            terms = re.findall(r"[\w]+", query)
            stop_words = {
                "a",
                "about",
                "above",
                "after",
                "again",
                "against",
                "all",
                "am",
                "an",
                "and",
                "any",
                "are",
                "aren't",
                "as",
                "at",
                "be",
                "because",
                "been",
                "before",
                "being",
                "below",
                "between",
                "both",
                "but",
                "by",
                "can't",
                "cannot",
                "could",
                "couldn't",
                "did",
                "didn't",
                "do",
                "does",
                "doesn't",
                "doing",
                "don't",
                "down",
                "during",
                "each",
                "few",
                "for",
                "from",
                "further",
                "had",
                "hadn't",
                "has",
                "hasn't",
                "have",
                "haven't",
                "having",
                "he",
                "he'd",
                "he'll",
                "he's",
                "her",
                "here",
                "here's",
                "hers",
                "herself",
                "him",
                "himself",
                "his",
                "how",
                "how's",
                "i",
                "i'd",
                "i'll",
                "i'm",
                "i've",
                "if",
                "in",
                "into",
                "is",
                "isn't",
                "it",
                "it's",
                "its",
                "itself",
                "let's",
                "me",
                "more",
                "most",
                "mustn't",
                "my",
                "myself",
                "no",
                "nor",
                "not",
                "of",
                "off",
                "on",
                "once",
                "only",
                "or",
                "other",
                "ought",
                "our",
                "ours",
                "ourselves",
                "out",
                "over",
                "own",
                "same",
                "shan't",
                "she",
                "she'd",
                "she'll",
                "she's",
                "should",
                "shouldn't",
                "so",
                "some",
                "such",
                "than",
                "that",
                "that's",
                "the",
                "their",
                "theirs",
                "them",
                "themselves",
                "then",
                "there",
                "there's",
                "these",
                "they",
                "they'd",
                "they'll",
                "they're",
                "they've",
                "this",
                "those",
                "through",
                "to",
                "too",
                "under",
                "until",
                "up",
                "very",
                "was",
                "wasn't",
                "we",
                "we'd",
                "we'll",
                "we're",
                "we've",
                "were",
                "weren't",
                "what",
                "what's",
                "when",
                "when's",
                "where",
                "where's",
                "which",
                "while",
                "who",
                "who's",
                "whom",
                "why",
                "why's",
                "with",
                "won't",
                "would",
                "wouldn't",
                "you",
                "you'd",
                "you'll",
                "you're",
                "you've",
                "your",
                "yours",
                "yourself",
                "yourselves",
            }
            keywords = [t for t in terms if t.lower() not in stop_words]
            if not keywords:
                keywords = terms

            fts_query = " OR ".join(f'"{kw}"*' for kw in keywords) if keywords else ""

            if fts_query:
                # First attempt FTS5 search
                try:
                    fts_rows = cursor.execute(
                        """
                        SELECT n.* FROM notes n
                        JOIN notes_fts f ON n.id = f.rowid
                        WHERE f.topic = ? AND n.status NOT IN ('closed', 'resolved')
                          AND (n.kind IS NULL OR LOWER(n.kind) != 'flag')
                          AND n.content NOT LIKE 'missed_%' AND n.content NOT LIKE 'pending_%'
                          AND notes_fts MATCH ?
                        ORDER BY rank
                        LIMIT 4
                    """,
                        (topic_slug, fts_query),
                    ).fetchall()
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
                rows = cursor.execute(
                    """
                    SELECT * FROM notes
                    WHERE topic = ? AND status NOT IN ('closed', 'resolved')
                      AND (kind IS NULL OR LOWER(kind) != 'flag')
                      AND content NOT LIKE 'missed_%' AND content NOT LIKE 'pending_%'
                    ORDER BY created_at DESC
                    LIMIT 4
                """,
                    (topic_slug,),
                ).fetchall()
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

    def compile_context(self, topic: str, query: str = "", token_budget: int = 1200, result_limit: int = 12) -> dict:
        ranked = self.rank_memories(topic, query, limit=result_limit)
        section_map = {
            "DECISION": "RELEVANT DECISIONS",
            "FACT": "CURRENT PROJECT FACTS",
            "CONSTRAINT": "IMPORTANT CONSTRAINTS",
            "DISCOVERY": "RECENT DISCOVERIES",
            "BUG": "RECENT DISCOVERIES",
            "WORKAROUND": "RECENT DISCOVERIES",
            "ARCHITECTURE": "RELEVANT HISTORY",
            "HISTORY": "RELEVANT HISTORY",
            "CONVENTION": "CURRENT PROJECT FACTS",
        }
        sections: dict[str, list[dict]] = {}
        used = 0
        for item in ranked:
            kind = str(item.get("kind") or "FACT").upper()
            section = section_map.get(kind, "CURRENT PROJECT FACTS")
            content = str(item.get("content") or "").strip()
            cost = max(1, (len(content) + 8) // 4)
            if used + cost > max(1, token_budget) or len(sections.setdefault(section, [])) >= result_limit:
                continue
            sections[section].append({"id": item.get("id"), "content": content, "score": item.get("score"), "kind": kind})
            used += cost
        return {"sections": sections, "token_count": used, "budget": token_budget, "ranked": ranked[:result_limit]}

    def build_agent_context(self, topic: str, query: str | None = None, result_limit: int = 5) -> str:
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

        lines.extend(
            [
                "",
                "## Code Intelligence",
                "Use code_find/code_read/code_explore/code_files (MCP) instead of grep/glob/read. "
                "Auto-index on first use; for plain text search use code_find(query, grep=True); "
                "empty results → code_init first. Review blast-radius: get_review_context(files).",
            ]
        )

        next_steps = list(metadata.get("next_steps", []))[::-1]
        single_step = metadata.get("next_step", "")
        if single_step:
            if single_step in next_steps:
                next_steps.remove(single_step)
            next_steps.insert(0, single_step)
        if next_steps:
            lines.extend(
                [
                    "",
                    "## Next Steps",
                    *[f"- {self._trim_text(step, 180)}" for step in next_steps[:3]],
                ]
            )

        all_notes = metadata.get("notes", [])
        pinned_notes = [n for n in all_notes if n.get("pinned")]
        if pinned_notes:
            lines.extend(
                [
                    "",
                    "## Pinned Notes",
                    *[f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 300)}" for n in pinned_notes],
                ]
            )

        session_lines = self._render_sessions_block(topic_slug)
        if session_lines:
            lines.extend(
                [
                    "",
                    "## Sessions",
                    *session_lines,
                ]
            )

        key_notes = self._get_key_notes(topic_slug, query)
        if key_notes:
            lines.extend(
                [
                    "",
                    "## Key Notes",
                    *[f"- [{n.get('kind', 'note')}] {self._trim_text(n.get('content') or n.get('title') or '', 300)}" for n in key_notes],
                ]
            )

        if query:
            related_ids = self.storage.search_nodes_fts(f"{topic_slug} {query}", limit=result_limit * 3)
            related_nodes = []
            for node_id in related_ids:
                node = self.storage.get_node(node_id)
                if not node:
                    continue
                related_nodes.append(node)
                if len(related_nodes) >= result_limit:
                    break

            if related_nodes:
                lines.extend(
                    [
                        "",
                        "## Query-Relevant Memories",
                        *[f"- [{node.node_type.value}] {node.title}: {self._trim_text(node.content, 300)}" for node in related_nodes],
                    ]
                )

        handoff = metadata.get("handoff")
        if handoff:
            lines.extend(
                [
                    "",
                    "## Handoff",
                    self._trim_text(handoff, 400),
                ]
            )

        compiled = self.compile_context(topic, query=query or "", token_budget=800, result_limit=result_limit)
        if compiled["sections"]:
            lines.extend(["", "## Compiled Memory Context"])
            for section, items in compiled["sections"].items():
                lines.append(f"### {section}")
                lines.extend(f"- {item['content']}" for item in items)

        # them (avoid re-injecting the same note on the first per-prompt recall).
        try:
            injected_ids = [n["id"] for n in (pinned_notes + key_notes) if isinstance(n.get("id"), int)]
            injected_ids = list(dict.fromkeys(injected_ids))
            if injected_ids:
                self._write_injected_notes_cache(topic_slug, injected_ids)
        except Exception:
            pass

        return "\n".join(lines)

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
                   WHERE f.topic = ? AND notes_fts MATCH ?"""
                + exclude_clause
                + """
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

    def rank_memories(self, topic: str, query: str, limit: int = 10, include_superseded: bool = False, historical: bool = False) -> list[dict]:
        historical_query = bool(re.search(r"\b(before|previously|formerly|historically|old|original)\b", query, re.I))
        historical = historical or historical_query
        if historical:
            include_superseded = True
        topic_tokens = self._tokenize(topic)
        query_tokens = self._tokenize(query)
        token_aliases = {
            "chose": "choose",
            "selected": "choose",
            "select": "choose",
            "technology": "choose",
            "requirements": "requirement",
            "payloads": "payload",
            "components": "component",
            "modules": "module",
            "failures": "failure",
            "fail": "failure",
            "discovered": "discover",
            "learned": "discover",
            "documented": "document",
        }

        def canonicalize(tokens: set[str]) -> set[str]:
            return {token_aliases.get(token, token.removesuffix("ing").removesuffix("ed")) for token in tokens}

        query_tokens = canonicalize(query_tokens)
        topic_tokens = canonicalize(topic_tokens)
        discriminative_tokens = query_tokens - topic_tokens
        if not discriminative_tokens:
            discriminative_tokens = query_tokens
        query_lower = query.lower()
        if re.search(r"\b(why|choose|chose|decision|approach)\b", query_lower):
            query_types = {"why_question", "decision"}
        elif historical_query:
            query_types = {"history", "historical", "supersession", "decision"}
        elif re.search(r"\b(constraint|requirement|must|limit|avoid)\b", query_lower):
            query_types = {"constraint"}
        elif re.search(r"\b(architecture|component|module|structure)\b", query_lower):
            query_types = {"architecture"}
        elif re.search(r"\b(workaround|fix|flaky|mitigate)\b", query_lower):
            query_types = {"workaround"}
        elif re.search(r"\b(bug|failure|error|regression)\b", query_lower):
            query_types = {"bug"}
        elif re.search(r"\b(discover|found|learned|root cause)\b", query_lower):
            query_types = {"discovery"}
        elif re.search(r"\b(file|symbol|implementation)\b", query_lower):
            query_types = {"code_related"}
        elif re.search(r"\b(supersed|old|former)\b", query_lower):
            query_types = {"supersession", "decision"}
        elif re.search(r"\b(scope|excluded|release)\b", query_lower):
            query_types = {"scope"}
        elif re.search(r"\b(ambiguous|unclear)\b", query_lower):
            query_types = {"ambiguous"}
        elif re.search(r"\b(stored|journal|direct fact)\b", query_lower):
            query_types = {"direct_fact"}
        elif re.search(r"\b(disagree|contradict)\b", query_lower):
            query_types = {"contradiction"}
        elif re.search(r"\b(prefer|preference)\b", query_lower):
            query_types = {"preference"}
        else:
            query_types = set()
        candidates = self.search_notes_fts(topic, query, limit=max(limit * 4, 20), exclude_ids=set())
        if query_types:
            placeholders = ",".join("?" for _ in query_types)
            candidates.extend(
                self.storage.connection.execute(
                    "SELECT id, topic, kind, content, title, created_at, tags, pinned FROM notes "
                    f"WHERE topic = ? AND UPPER(kind) IN ({placeholders}) AND COALESCE(status, 'open') != 'superseded' "
                    "ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    (self.normalize_topic(topic), *sorted(query_types), max(limit * 2, 10)),
                ).fetchall()
            )
        results: list[dict] = []
        seen: set[int] = set()
        now = datetime.now(timezone.utc)
        for row in candidates:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            full = self.get_note(row["id"])
            if not full or (not include_superseded and full.get("status") == "superseded"):
                continue
            valid_until = full.get("valid_until")
            valid_from = full.get("valid_from")
            if not historical and valid_until:
                try:
                    if datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")) < now:
                        continue
                except ValueError:
                    pass
            if not historical and valid_from:
                try:
                    if datetime.fromisoformat(str(valid_from).replace("Z", "+00:00")) > now:
                        continue
                except ValueError:
                    pass
            content_tokens = canonicalize(self._tokenize(str(full.get("content", ""))))
            overlap = len(discriminative_tokens & content_tokens)
            kind = str(full.get("kind", "fact")).lower()
            if historical_query and kind not in query_types:
                continue
            if not overlap and kind not in query_types:
                continue
            lexical = overlap / max(1, len(discriminative_tokens))
            phrase_bonus = 0.25 if query.strip().lower() in str(full.get("content", "")).lower() else 0.0
            fts_score = min(1.0, lexical + phrase_bonus)
            importance_score = max(0.0, min(1.0, float(full.get("importance") or 0.0)))
            confidence_score = max(0.0, min(1.0, float(full.get("confidence") or 0.0)))
            graph_score = min(1.0, len(self.get_note_neighbors(full["id"], direction="out")) / 10.0)
            temporal_score = 1.0 if not valid_until else 0.2
            superseded = full.get("status") == "superseded"
            supersession_score = 1.0 if historical and superseded else (0.65 if historical else 1.0)
            kind = str(full.get("kind", "fact")).lower()
            query_lower = query.lower()
            type_terms = {
                "decision": ("choose", "chose", "decision", "approach", "selected"),
                "why_question": ("why", "reason", "cause"),
                "direct_fact": ("stored", "journal", "direct", "fact"),
                "constraint": ("must", "constraint", "limit", "requirement", "avoid"),
                "architecture": ("architecture", "component", "module", "structure"),
                "bug": ("bug", "failure", "error", "regression"),
                "workaround": ("workaround", "fix", "flaky", "mitigate"),
                "discovery": ("discover", "found", "learned", "root cause"),
                "code": ("file", "symbol", "implementation", "module"),
                "history": ("before", "previous", "formerly", "histor", "original"),
            }
            type_score = max((1.0 if any(term in query_lower for term in terms) and kind == name else 0.0 for name, terms in type_terms.items()), default=0.0)
            if historical and kind in {"history", "supersession", "decision", "fact"}:
                type_score = max(type_score, 0.8 if kind in {"history", "supersession"} else 0.5)
            components = {
                "fts": round(fts_score, 4),
                "fts_score": round(fts_score, 4),
                "metadata": round(0.5 * importance_score + 0.3 * confidence_score + 0.2 * lexical, 4),
                "importance_score": round(importance_score, 4),
                "confidence_score": round(confidence_score, 4),
                "type_score": round(type_score, 4),
                "graph": round(graph_score, 4),
                "graph_score": round(graph_score, 4),
                "temporal": temporal_score,
                "temporal_score": temporal_score,
                "supersession": supersession_score,
                "supersession_score": supersession_score,
            }
            final_score = (
                0.35 * fts_score
                + 0.15 * type_score
                + 0.15 * importance_score
                + 0.1 * confidence_score
                + 0.1 * graph_score
                + 0.075 * temporal_score
                + 0.075 * supersession_score
            )
            components["final_score"] = round(final_score, 4)
            results.append({**full, "score": round(final_score, 4), "final_score": round(final_score, 4), "score_components": components})
        results.sort(key=lambda item: item["score"], reverse=True)
        for item in results[:limit]:
            self.storage.connection.execute(
                "INSERT INTO memory_access_log(topic,note_id,query,outcome) VALUES(?,?,?,'retrieved')", (self.normalize_topic(topic), item["id"], query)
            )
        self.storage.connection.commit()
        return results[:limit]

    def search_notes(self, topic: str, kind: str = "", query: str = "", tags: str = "", limit: int = 10) -> list[dict]:
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
                    params.append(f'%"{tag}"%')
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
            "SELECT id, topic, kind, content, title FROM notes WHERE " + " OR ".join(field_match(field) for field in ("content", "title")) + " LIMIT ?",
            term_params * 2 + [limit],
        ).fetchall()
        notes = [dict(r) for r in note_rows]

        return {"planets": planets, "notes": notes}

    def reinforce_link(self, from_note_id: int, to_note_id: int, increment: float = 0.05):

        from_id, to_id = sorted([from_note_id, to_note_id])
        cursor = self.storage.connection.cursor()
        row = cursor.execute(
            "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type IN ('auto', 'lexical_related')",
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
            notes = cursor.execute("SELECT id, content, scope, source_path FROM notes WHERE topic = ?", (self.normalize_topic(topic),)).fetchall()
        else:
            notes = cursor.execute("SELECT id, content, scope, source_path FROM notes").fetchall()
        created = 0
        removed = 0
        for i in range(len(notes)):
            for j in range(i + 1, len(notes)):
                if notes[i]["scope"] and notes[j]["scope"] and notes[i]["scope"] != notes[j]["scope"]:
                    continue
                entity_i = notes[i]["source_path"] or notes[i]["scope"] or ""
                entity_j = notes[j]["source_path"] or notes[j]["scope"] or ""
                if entity_i and entity_j and entity_i != entity_j:
                    continue
                wa = self._tokenize(notes[i]["content"])
                wb = self._tokenize(notes[j]["content"])
                if len(wa) < 3 or len(wb) < 3:
                    continue
                intersection = wa & wb
                union = wa | wb
                score = len(intersection) / len(union) if union else 0
                from_id, to_id = sorted([notes[i]["id"], notes[j]["id"]])
                existing = cursor.execute(
                    "SELECT weight FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type IN ('auto', 'lexical_related')",
                    (from_id, to_id),
                ).fetchone()
                if score >= threshold:
                    confidence = round(min(1.0, score * 1.5), 3)
                    if confidence < self.AUTO_LINK_MIN_CONFIDENCE:
                        continue
                    provenance = json.dumps({"method": "lexical_similarity", "semantic": False, "score": round(score, 3)})
                    if existing:
                        new_weight = round((existing["weight"] + score) / 2, 3)
                        exec_stmt(
                            self.storage.connection,
                            "UPDATE note_links SET weight = ?, confidence = ?, updated_at = ? "
                            "WHERE from_note_id = ? AND to_note_id = ? AND link_type IN ('auto', 'lexical_related')",
                            (new_weight, confidence, self._now(), from_id, to_id),
                        )
                    else:
                        exec_stmt(
                            self.storage.connection,
                            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, confidence, source, "
                            "provenance, created_at, updated_at) VALUES (?, ?, 'lexical_related', ?, ?, 'auto', ?, ?, ?)",
                            (from_id, to_id, round(score, 3), confidence, provenance, self._now(), self._now()),
                        )
                        created += 1
                elif existing and score < min_weight:
                    exec_stmt(
                        self.storage.connection,
                        "DELETE FROM note_links WHERE from_note_id = ? AND to_note_id = ? AND link_type IN ('auto', 'lexical_related')",
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
