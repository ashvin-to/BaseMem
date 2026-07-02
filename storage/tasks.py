"""Task operations — task tracking stored in tasks table."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from storage.db import StorageManager


def _get_tasks(conn: sqlite3.Connection, topic: str) -> list[dict]:
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT * FROM tasks WHERE topic = ? ORDER BY created_at DESC",
        (topic,),
    ).fetchall()
    return [dict(r) for r in rows]


def _exec(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> None:
    conn.execute(sql, params)
    conn.commit()


class TaskMixin:
    """Mixin providing task CRUD methods. Requires self.storage (StorageManager)."""

    storage: StorageManager
    normalize_topic: Any
    _now: Any
    get_or_create_task_planet: Any

    VALID_STATUSES = {"todo", "in_progress", "blocked", "done"}
    VALID_PRIORITIES = {"low", "medium", "high"}

    def _check_dependency_cycle(self, task_id: int, depends_on: list[int], visited: set | None = None) -> bool:
        if visited is None:
            visited = set()
        for dep_id in depends_on:
            if dep_id == task_id:
                return True
            if dep_id in visited:
                continue
            visited.add(dep_id)
            cursor = self.storage.connection.cursor()
            row = cursor.execute(
                "SELECT depends_on FROM tasks WHERE id = ?", (dep_id,)
            ).fetchone()
            if row:
                nested = json.loads(row["depends_on"])
                if self._check_dependency_cycle(task_id, nested, visited):
                    return True
        return False

    def get_task_summary(self, topic: str) -> dict:
        cursor = self.storage.connection.cursor()
        slug = self.normalize_topic(topic)
        rows = cursor.execute(
            "SELECT status, COUNT(*) AS cnt FROM tasks WHERE topic = ? GROUP BY status",
            (slug,),
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        return {"total": total, "counts": counts}

    def create_task(
        self,
        topic: str,
        title: str,
        priority: str = "medium",
        depends_on: list[int] | None = None,
        files: list[str] | None = None,
        notes: list[int] | None = None,
    ) -> dict:
        from .planets import _exec as _pexec
        from .planets import _get_planet_row

        topic_slug = self.normalize_topic(topic)
        row = _get_planet_row(self.storage.connection, topic_slug)
        if not row:
            self.get_or_create_task_planet(topic, topic)
        priority = priority.lower() if priority in self.VALID_PRIORITIES else "medium"
        deps = sorted(set(int(d) for d in depends_on)) if depends_on else []
        if deps:
            existing = set()
            cursor = self.storage.connection.cursor()
            for d in deps:
                r = cursor.execute("SELECT id FROM tasks WHERE id = ?", (d,)).fetchone()
                if r:
                    existing.add(d)
            deps = sorted(existing)
        file_list = sorted(set(files)) if files else []
        note_list = sorted(set(int(n) for n in notes)) if notes else []
        now = self._now()
        _pexec(
            self.storage.connection,
            "INSERT INTO tasks (topic, title, status, priority, depends_on, files, notes, created_at) VALUES (?, ?, 'todo', ?, ?, ?, ?, ?)",
            (topic_slug, title, priority, json.dumps(deps), json.dumps(file_list), json.dumps(note_list), now),
        )
        _pexec(
            self.storage.connection,
            "UPDATE planets SET updated_at = ? WHERE topic = ?",
            (now, topic_slug),
        )
        cursor = self.storage.connection.cursor()
        task_row = cursor.execute(
            "SELECT * FROM tasks WHERE topic = ? AND title = ? AND created_at = ? ORDER BY id DESC LIMIT 1",
            (topic_slug, title, now),
        ).fetchone()
        return dict(task_row) if task_row else {"title": title, "topic": topic_slug}

    def update_task(
        self,
        task_id: int,
        status: str | None = None,
        priority: str | None = None,
        depends_on: list[int] | None = None,
        files: list[str] | None = None,
        notes: list[int] | None = None,
    ) -> tuple[bool, str]:
        from .planets import _exec as _pexec

        cursor = self.storage.connection.cursor()
        row = cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return False, f"Task not found: {task_id}"
        task = dict(row)
        updates = []
        params: list = []
        if status is not None:
            s = status.lower().strip()
            if s not in self.VALID_STATUSES:
                return False, f"Invalid status: {status}. Valid: {', '.join(sorted(self.VALID_STATUSES))}"
            updates.append("status = ?")
            params.append(s)
            if s == "done":
                updates.append("completed_at = ?")
                params.append(self._now())
            elif task.get("completed_at"):
                updates.append("completed_at = NULL")
        if priority is not None:
            p = priority.lower().strip()
            if p not in self.VALID_PRIORITIES:
                return False, f"Invalid priority: {priority}. Valid: {', '.join(sorted(self.VALID_PRIORITIES))}"
            updates.append("priority = ?")
            params.append(p)
        if depends_on is not None:
            deps = sorted(set(int(d) for d in depends_on))
            for d in deps:
                r = cursor.execute("SELECT id FROM tasks WHERE id = ?", (d,)).fetchone()
                if r is None:
                    return False, f"Dependency task not found: {d}"
            if self._check_dependency_cycle(task_id, deps):
                return False, "Cannot set depends_on: would create a dependency cycle"
            updates.append("depends_on = ?")
            params.append(json.dumps(deps))
        if files is not None:
            updates.append("files = ?")
            params.append(json.dumps(sorted(set(files))))
        if notes is not None:
            updates.append("notes = ?")
            params.append(json.dumps([int(n) for n in sorted(set(notes))]))
        if updates:
            params.append(task_id)
            _pexec(
                self.storage.connection,
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            _pexec(
                self.storage.connection,
                "UPDATE planets SET updated_at = ? WHERE topic = ?",
                (self._now(), task["topic"]),
            )
        return True, f"Task {task_id} updated"

    def list_tasks(
        self, topic: str | None = None, status: str | None = None, priority: str | None = None
    ) -> list[dict]:
        cursor = self.storage.connection.cursor()
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if topic:
            sql += " AND topic = ?"
            params.append(self.normalize_topic(topic))
        if status:
            s = status.lower().strip()
            if s in self.VALID_STATUSES:
                sql += " AND status = ?"
                params.append(s)
        if priority:
            p = priority.lower().strip()
            if p in self.VALID_PRIORITIES:
                sql += " AND priority = ?"
                params.append(p)
        sql += " ORDER BY created_at DESC"
        rows = cursor.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def edge_decay(self, factor: float = 0.9, planet: str | None = None) -> dict:

        cursor = self.storage.connection.cursor()
        if planet:
            slug = self.normalize_topic(planet)
            note_ids = [
                r["id"]
                for r in cursor.execute(
                    "SELECT id FROM notes WHERE topic = ?", (slug,)
                ).fetchall()
            ]
            if not note_ids:
                return {"decayed": 0, "factor": factor, "message": "No notes in planet"}
            placeholders = ",".join("?" for _ in note_ids)
            affected = cursor.execute(
                f"UPDATE note_links SET weight = ROUND(weight * ?, 3), updated_at = ? "
                f"WHERE (from_note_id IN ({placeholders}) OR to_note_id IN ({placeholders})) AND source = 'auto'",
                (factor, self._now(), *note_ids, *note_ids),
            ).rowcount
        else:
            affected = cursor.execute(
                "UPDATE note_links SET weight = ROUND(weight * ?, 3), updated_at = ? WHERE source = 'auto'",
                (factor, self._now()),
            ).rowcount
        self.storage.connection.commit()
        return {"decayed": affected, "factor": factor}

    def edge_prune(self, threshold: float = 0.05, planet: str | None = None) -> dict:
        cursor = self.storage.connection.cursor()
        if planet:
            slug = self.normalize_topic(planet)
            note_ids = [
                r["id"]
                for r in cursor.execute(
                    "SELECT id FROM notes WHERE topic = ?", (slug,)
                ).fetchall()
            ]
            if not note_ids:
                return {"pruned": 0, "threshold": threshold, "message": "No notes in planet"}
            placeholders = ",".join("?" for _ in note_ids)
            affected = cursor.execute(
                f"DELETE FROM note_links WHERE weight < ? AND source = 'auto' "
                f"AND (from_note_id IN ({placeholders}) OR to_note_id IN ({placeholders}))",
                (threshold, *note_ids, *note_ids),
            ).rowcount
        else:
            affected = cursor.execute(
                "DELETE FROM note_links WHERE weight < ? AND source = 'auto'",
                (threshold,),
            ).rowcount
        self.storage.connection.commit()
        return {"pruned": affected, "threshold": threshold}
