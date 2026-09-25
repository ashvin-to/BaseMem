from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = ((1, "legacy-task-archive"), (2, "session-task-id-cleanup"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _json_list(value):
    try:
        result = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return result if isinstance(result, list) else []


def prepare_backup(conn, db_path: str | Path) -> str | None:
    path = Path(db_path)
    if not path.exists():
        return None
    backup = Path(str(path) + ".v1.bak")
    if backup.exists():
        return str(backup)
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(str(backup))
    try:
        conn.backup(destination)
    finally:
        destination.close()
    return str(backup)


def _archive_tasks(conn):
    tables = _tables(conn)
    if "tasks_legacy_v1" not in tables:
        if "tasks" in tables:
            conn.execute("ALTER TABLE tasks RENAME TO tasks_legacy_v1")
        else:
            conn.execute("CREATE TABLE tasks_legacy_v1 (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo', priority TEXT NOT NULL DEFAULT 'medium', depends_on TEXT DEFAULT '[]', files TEXT DEFAULT '[]', notes TEXT DEFAULT '[]', created_at TEXT DEFAULT (datetime('now')), completed_at TEXT)")
    legacy = conn.execute("SELECT * FROM tasks_legacy_v1 ORDER BY id").fetchall()
    sessions = _tables(conn) & {"sessions"}
    session_rows = conn.execute("SELECT * FROM sessions").fetchall() if sessions else []
    for task in legacy:
        task_values = {key: task[key] if key in task.keys() else None for key in ("topic", "title", "status", "priority", "depends_on", "files", "notes", "created_at", "completed_at")}
        task_id = task["id"]
        topic = task_values["topic"] or "general"
        title = task_values["title"] or f"Task {task_id}"
        content = "\n".join([
            f"Legacy task: {title}",
            f"Task ID: {task_id}",
            f"Status: {task_values['status'] or ''}",
            f"Priority: {task_values['priority'] or ''}",
            f"Depends on: {task_values['depends_on'] or '[]'}",
            f"Files: {task_values['files'] or '[]'}",
            f"Notes: {task_values['notes'] or '[]'}",
            f"Created: {task_values['created_at'] or ''}",
            f"Completed: {task_values['completed_at'] or ''}",
        ])
        provenance = {"task_id": task_id, **{key: task_values[key] for key in task_values}}
        existing = None
        for note in conn.execute("SELECT id, provenance FROM notes WHERE topic=?", (topic,)).fetchall():
            try:
                candidate = json.loads(note["provenance"] or "{}")
            except (TypeError, json.JSONDecodeError):
                candidate = {}
            if candidate.get("task_id") == task_id:
                existing = note["id"]
                break
        if existing is None:
            created = task_values["created_at"] or _now()
            cursor = conn.execute(
                "INSERT INTO notes(topic,kind,content,title,agent_id,status,importance,confidence,source,provenance,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (topic, "TASK_ARCHIVE", content, title, "migration", "archived", 0.4, 1.0, "tasks_legacy_v1", json.dumps(provenance), created, created),
            )
            note_id = cursor.lastrowid
        else:
            note_id = existing
            conn.execute(
                "UPDATE notes SET kind=?, content=?, title=?, status=?, source=?, provenance=?, updated_at=? WHERE id=?",
                ("TASK_ARCHIVE", content, title, "archived", "tasks_legacy_v1", json.dumps(provenance), _now(), note_id),
            )
        for session in session_rows:
            if session["topic"] != topic:
                continue
            note_ids = _json_list(session["note_ids"])
            task_ids = _json_list(session["task_ids"]) if "task_ids" in session.keys() else []
            if task_id in task_ids and note_id not in note_ids:
                note_ids.append(note_id)
            conn.execute("UPDATE sessions SET note_ids=? WHERE id=?", (json.dumps(note_ids), session["id"]))
    return len(legacy)


def run_migrations(conn, db_path: str | Path | None = None) -> dict:
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    conn.commit()
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    report = {"applied": [], "skipped": [], "backup_path": None, "task_rows": 0}
    for version, name in MIGRATIONS:
        if version in applied:
            report["skipped"].append(version)
            continue
        if version == 1:
            if db_path and Path(db_path).exists() and not report["backup_path"]:
                report["backup_path"] = prepare_backup(conn, db_path)
            if "notes" in _tables(conn):
                if "importance" not in _columns(conn, "notes"):
                    conn.execute("ALTER TABLE notes ADD COLUMN importance REAL DEFAULT 0.5")
                for column, definition in (("confidence", "REAL DEFAULT 0.5"), ("scope", "TEXT DEFAULT ''"), ("source", "TEXT DEFAULT ''"), ("provenance", "TEXT DEFAULT '{}'"), ("valid_from", "TEXT"), ("valid_until", "TEXT"), ("supersedes", "INTEGER"), ("superseded_by", "INTEGER")):
                    if column not in _columns(conn, "notes"):
                        conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")
            if "note_links" in _tables(conn) and "provenance" not in _columns(conn, "note_links"):
                conn.execute("ALTER TABLE note_links ADD COLUMN provenance TEXT DEFAULT '{}'")
            if "notes" in _tables(conn):
                report["task_rows"] = _archive_tasks(conn)
        if version == 2 and "sessions" in _tables(conn) and "task_ids" in _columns(conn, "sessions"):
            conn.execute("ALTER TABLE sessions DROP COLUMN task_ids")
        conn.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (version, name, _now()))
        conn.commit()
        report["applied"].append(version)
    return report
