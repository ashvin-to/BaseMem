from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS = ((1, "legacy-task-archive"), (2, "session-task-id-cleanup"))


class MigrationError(RuntimeError):
    """A migration could not be completed safely."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _json_list(value):
    try:
        result = json.loads(value if value is not None else "[]")
    except (TypeError, json.JSONDecodeError):
        return None
    return result if isinstance(result, list) else None


def prepare_backup(conn, db_path: str | Path) -> str | None:
    """Create a consistent SQLite backup without replacing an earlier snapshot.

    The backup is a logical database copy, not a copy of WAL or SHM sidecars.
    Callers must serialize migrations with other writers for the interval between
    this snapshot and the migration transaction.
    """
    path = Path(db_path)
    if not path.exists():
        return None
    backup = Path(f"{path}.v1.bak")
    if backup.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = Path(f"{path}.v1.{stamp}.bak")
        suffix = 1
        while backup.exists():
            backup = Path(f"{path}.v1.{stamp}-{suffix}.bak")
            suffix += 1
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(str(backup))
    try:
        conn.backup(destination)
    except Exception:
        destination.close()
        backup.unlink(missing_ok=True)
        raise
    destination.close()
    return str(backup)


def _archive_tasks(conn):
    tables = _tables(conn)
    if "tasks_legacy_v1" not in tables:
        if "tasks" in tables:
            conn.execute("ALTER TABLE tasks RENAME TO tasks_legacy_v1")
        else:
            conn.execute(
                "CREATE TABLE tasks_legacy_v1 ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, title TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'todo', priority TEXT NOT NULL DEFAULT 'medium', "
                "depends_on TEXT DEFAULT '[]', files TEXT DEFAULT '[]', notes TEXT DEFAULT '[]', "
                "created_at TEXT DEFAULT (datetime('now')), completed_at TEXT)"
            )
    legacy = conn.execute("SELECT * FROM tasks_legacy_v1 ORDER BY id").fetchall()
    if "sessions" not in _tables(conn):
        return len(legacy)
    session_rows = conn.execute("SELECT * FROM sessions").fetchall()
    session_task_ids = {}
    session_note_ids = {}
    archive_by_task = {}
    for note in conn.execute("SELECT id, topic, provenance FROM notes").fetchall():
        try:
            candidate = json.loads(note["provenance"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and "task_id" in candidate:
            archive_by_task.setdefault((note["topic"], candidate["task_id"]), note["id"])

    for task in legacy:
        keys = ("topic", "title", "status", "priority", "depends_on", "files", "notes", "created_at", "completed_at")
        task_keys = set(task.keys())
        task_values = {key: task[key] if key in task_keys else None for key in keys}
        task_id = task["id"]
        topic = task_values["topic"] or "general"
        title = task_values["title"] or f"Task {task_id}"
        content = "\n".join(
            [
                f"Legacy task: {title}",
                f"Task ID: {task_id}",
                f"Status: {task_values['status'] or ''}",
                f"Priority: {task_values['priority'] or ''}",
                f"Depends on: {task_values['depends_on'] or '[]'}",
                f"Files: {task_values['files'] or '[]'}",
                f"Notes: {task_values['notes'] or '[]'}",
                f"Created: {task_values['created_at'] or ''}",
                f"Completed: {task_values['completed_at'] or ''}",
            ]
        )
        provenance = {"task_id": task_id, **{key: task_values[key] for key in task_values}}
        note_id = archive_by_task.get((topic, task_id))
        if note_id is None:
            created = task_values["created_at"] or _now()
            cursor = conn.execute(
                "INSERT INTO notes(topic,kind,content,title,agent_id,status,importance,confidence,source,provenance,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    topic,
                    "TASK_ARCHIVE",
                    content,
                    title,
                    "migration",
                    "archived",
                    0.4,
                    1.0,
                    "tasks_legacy_v1",
                    json.dumps(provenance),
                    created,
                    created,
                ),
            )
            note_id = cursor.lastrowid
            archive_by_task[(topic, task_id)] = note_id
        else:
            conn.execute(
                "UPDATE notes SET kind=?, content=?, title=?, status=?, source=?, provenance=?, updated_at=? WHERE id=?",
                ("TASK_ARCHIVE", content, title, "archived", "tasks_legacy_v1", json.dumps(provenance), _now(), note_id),
            )

        for session in session_rows:
            session_id = session["id"]
            session_keys = set(session.keys())
            if session["topic"] != topic or "task_ids" not in session_keys:
                continue
            if session_id not in session_task_ids:
                session_task_ids[session_id] = _json_list(session["task_ids"])
                session_note_ids[session_id] = _json_list(session["note_ids"])
            task_ids = session_task_ids[session_id]
            note_ids = session_note_ids[session_id]
            if task_ids is None or note_ids is None or task_id not in task_ids:
                continue
            if note_id not in note_ids:
                note_ids.append(note_id)
                conn.execute("UPDATE sessions SET note_ids=? WHERE id=?", (json.dumps(note_ids), session_id))
    return len(legacy)


def _apply_migration(conn, version):
    if version == 1:
        if "notes" in _tables(conn):
            if "importance" not in _columns(conn, "notes"):
                conn.execute("ALTER TABLE notes ADD COLUMN importance REAL DEFAULT 0.5")
            additions = (
                ("confidence", "REAL DEFAULT 0.5"),
                ("scope", "TEXT DEFAULT ''"),
                ("source", "TEXT DEFAULT ''"),
                ("provenance", "TEXT DEFAULT '{}'"),
                ("valid_from", "TEXT"),
                ("valid_until", "TEXT"),
                ("supersedes", "INTEGER"),
                ("superseded_by", "INTEGER"),
            )
            for column, definition in additions:
                if column not in _columns(conn, "notes"):
                    conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")
        if "note_links" in _tables(conn) and "provenance" not in _columns(conn, "note_links"):
            conn.execute("ALTER TABLE note_links ADD COLUMN provenance TEXT DEFAULT '{}'")
        if "notes" in _tables(conn):
            return _archive_tasks(conn)
    elif version == 2 and "sessions" in _tables(conn) and "task_ids" in _columns(conn, "sessions"):
        conn.execute("ALTER TABLE sessions DROP COLUMN task_ids")
    return 0


def run_migrations(conn, db_path: str | Path | None = None) -> dict[str, Any]:
    """Apply pending migrations with one explicit transaction per version.

    SQLite can commit DDL transactionally on supported builds, so each version
    and its bookkeeping commit or roll back together. The whole migration set is
    not atomic, downgrades are unsupported, and SQLite older than 3.35 cannot run
    migration 2's DROP COLUMN operation. In-memory databases and callers that
    omit ``db_path`` cannot be backed up. Any transaction already active on the
    connection is committed before migration bookkeeping starts. SQLite foreign-key
    enforcement may reject a schema change depending on the legacy schema and runtime.
    """
    conn.row_factory = sqlite3.Row
    if conn.in_transaction:
        try:
            conn.commit()
        except Exception as exc:
            raise MigrationError(f"Unable to finish the caller's active transaction: {exc}") from exc

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        conn.commit()
    except Exception as exc:
        if conn.in_transaction:
            conn.rollback()
        raise MigrationError(f"Unable to initialize schema migration bookkeeping: {exc}") from exc

    report: dict[str, Any] = {"applied": [], "skipped": [], "backup_path": None, "task_rows": 0}
    for version, name in MIGRATIONS:
        if version in applied:
            report["skipped"].append(version)
            continue
        if report["backup_path"] is None and db_path is not None:
            try:
                report["backup_path"] = prepare_backup(conn, db_path)
            except Exception as exc:
                raise MigrationError(f"Backup required before migration {version} ({name}) failed: {exc}") from exc

        try:
            conn.execute("BEGIN IMMEDIATE")
            task_rows = _apply_migration(conn, version)
            conn.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (version, name, _now()),
            )
            conn.commit()
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
            backup = report["backup_path"] or "not created"
            raise MigrationError(
                f"Migration {version} ({name}) failed and was rolled back; backup: {backup}; cause: {exc}"
            ) from exc
        report["applied"].append(version)
        if version == 1:
            report["task_rows"] = task_rows
    return report
