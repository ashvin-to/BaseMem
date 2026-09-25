from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = ((1, "legacy-task-archive"),)

NOTE_TYPES = (
    "FACT", "DECISION", "CONSTRAINT", "PREFERENCE", "DISCOVERY", "BUG",
    "WORKAROUND", "ARCHITECTURE", "CONVENTION", "HYPOTHESIS", "HISTORY",
    "SUMMARY", "TURN", "ISSUE", "QUESTION", "TASK_ARCHIVE",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def prepare_backup(conn, db_path: str | Path) -> str | None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_migrations" in tables and conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
        return None
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
                backup = Path(str(db_path) + ".v1.bak")
                if not backup.exists():
                    prepare_backup(conn, db_path)
                report["backup_path"] = str(backup)
            conn.execute("ALTER TABLE notes ADD COLUMN importance REAL DEFAULT 0.5")
            for column, definition in (("confidence", "REAL DEFAULT 0.5"), ("scope", "TEXT DEFAULT ''"), ("source", "TEXT DEFAULT ''"), ("provenance", "TEXT DEFAULT '{}'"), ("valid_from", "TEXT"), ("valid_until", "TEXT"), ("supersedes", "INTEGER"), ("superseded_by", "INTEGER")):
                if column not in _columns(conn, "notes"):
                    conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")
            if "provenance" not in _columns(conn, "note_links"):
                conn.execute("ALTER TABLE note_links ADD COLUMN provenance TEXT DEFAULT '{}'")
            if "tasks_legacy_v1" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                if "tasks" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    conn.execute("ALTER TABLE tasks RENAME TO tasks_legacy_v1")
                else:
                    conn.execute("CREATE TABLE tasks_legacy_v1 (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo', priority TEXT NOT NULL DEFAULT 'medium', depends_on TEXT DEFAULT '[]', files TEXT DEFAULT '[]', notes TEXT DEFAULT '[]', created_at TEXT DEFAULT (datetime('now')), completed_at TEXT)")
            legacy = conn.execute("SELECT * FROM tasks_legacy_v1 ORDER BY id").fetchall()
            report["task_rows"] = len(legacy)
            for task in legacy:
                if conn.execute("SELECT 1 FROM notes WHERE content = ? AND topic = ?", (f"Legacy task: {task['title']}", task['topic'])).fetchone():
                    continue
                conn.execute("INSERT INTO notes(topic,kind,content,title,agent_id,status,importance,confidence,source,provenance,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (task['topic'], 'TASK_ARCHIVE', f"Legacy task: {task['title']}\nStatus: {task['status']}\nPriority: {task['priority']}\nDepends on: {task['depends_on'] or '[]'}\nFiles: {task['files'] or '[]'}\nNotes: {task['notes'] or '[]'}\nCompleted: {task['completed_at'] or ''}", task['title'], 'migration', 'archived', 0.4, 1.0, 'tasks_legacy_v1', json.dumps({"task_id": task['id'], "status": task['status'], "priority": task['priority'], "depends_on": task['depends_on'], "files": task['files'], "notes": task['notes'], "completed_at": task['completed_at']}), task['created_at'] or _now(), task['created_at'] or _now()))
                note_id = conn.execute("SELECT id FROM notes WHERE topic=? AND title=? ORDER BY id DESC LIMIT 1", (task['topic'], task['title'])).fetchone()[0]
                if "sessions" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    session_columns = _columns(conn, "sessions")
                    selected = "id,note_ids" + (",task_ids" if "task_ids" in session_columns else "")
                    for row in conn.execute(f"SELECT {selected} FROM sessions WHERE topic=?", (task['topic'],)).fetchall():
                        try: ids = json.loads(row['note_ids'] or '[]')
                        except (TypeError, json.JSONDecodeError): ids = []
                        try: task_refs = json.loads(row['task_ids'] or '[]') if 'task_ids' in row.keys() else []
                        except (TypeError, json.JSONDecodeError): task_refs = []
                        if task['id'] in task_refs and note_id not in ids: ids.append(note_id)
                        conn.execute("UPDATE sessions SET note_ids=? WHERE id=?", (json.dumps(ids), row['id']))
            conn.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (version, name, _now()))
        conn.commit()
        report["applied"].append(version)
    return report
