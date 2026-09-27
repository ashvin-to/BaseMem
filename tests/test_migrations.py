from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

import storage.migrations as migrations
from cli.main import cli
from storage.migrations import MigrationError, run_migrations


def _create_legacy_db(path: Path, task_count: int = 1) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            title TEXT DEFAULT '',
            agent_id TEXT DEFAULT 'default',
            status TEXT DEFAULT 'open',
            provenance TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'todo',
            priority TEXT NOT NULL DEFAULT 'medium',
            depends_on TEXT DEFAULT '[]',
            files TEXT DEFAULT '[]',
            notes TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            note_ids TEXT NOT NULL DEFAULT '[]',
            task_ids TEXT NOT NULL DEFAULT '[]'
        );
        """
    )
    conn.executemany(
        "INSERT INTO tasks(topic,title,depends_on,files,notes) VALUES(?,?,?,?,?)",
        [(f"topic-{index}", f"Task {index}", f"[{index}]", f'["task-{index}.py"]', f'["note-{index}"]') for index in range(task_count)],
    )
    conn.commit()
    return conn


def _versions(conn: sqlite3.Connection) -> list[int]:
    return [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]


def test_fresh_database_migrates_with_explicit_transactions_and_backup(tmp_path):
    db_path = tmp_path / "fresh.db"
    conn = sqlite3.connect(db_path)
    statements = []
    conn.set_trace_callback(statements.append)

    report = run_migrations(conn, db_path)

    assert report["applied"] == [1, 2]
    assert report["skipped"] == []
    assert report["task_rows"] == 0
    assert report["backup_path"] and Path(report["backup_path"]).exists()
    assert _versions(conn) == [1, 2]
    assert sum(statement.strip().upper() == "BEGIN IMMEDIATE" for statement in statements) == 3
    conn.close()


def test_legacy_tasks_and_existing_archive_are_preserved(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = _create_legacy_db(db_path)
    conn.execute(
        "INSERT INTO notes(topic,kind,content,title,agent_id,provenance) VALUES(?,?,?,?,?,?)",
        ("topic-0", "TASK_ARCHIVE", "sentinel", "keep me", "original-agent", json.dumps({"task_id": 1})),
    )
    existing_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO notes(topic,content) VALUES(?,?)", ("unrelated", "must survive"))
    unrelated_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    report = run_migrations(conn, db_path)

    assert report["task_rows"] == 1
    assert conn.execute("SELECT agent_id FROM notes WHERE id=?", (existing_id,)).fetchone()[0] == "original-agent"
    assert conn.execute("SELECT content FROM notes WHERE id=?", (unrelated_id,)).fetchone()[0] == "must survive"
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE kind='TASK_ARCHIVE'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tasks_legacy_v1").fetchone()[0] == 1
    conn.close()


def test_already_migrated_database_is_idempotent_and_preserves_archive(tmp_path):
    db_path = tmp_path / "migrated.db"
    conn = _create_legacy_db(db_path)
    first = run_migrations(conn, db_path)
    archive_count = conn.execute("SELECT COUNT(*) FROM notes WHERE kind='TASK_ARCHIVE'").fetchone()[0]

    second = run_migrations(conn, db_path)

    assert first["applied"] == [1, 2]
    assert second["applied"] == []
    assert second["skipped"] == [1, 2]
    assert second["backup_path"] is None
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE kind='TASK_ARCHIVE'").fetchone()[0] == archive_count
    conn.close()


def test_empty_tasks_table_is_safely_archived(tmp_path):
    db_path = tmp_path / "empty.db"
    conn = _create_legacy_db(db_path, task_count=0)
    conn.execute("DELETE FROM tasks")
    conn.commit()

    report = run_migrations(conn, db_path)

    assert report["task_rows"] == 0
    assert "tasks_legacy_v1" in migrations._tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM tasks_legacy_v1").fetchone()[0] == 0
    conn.close()


def test_malformed_session_json_is_not_overwritten(tmp_path):
    db_path = tmp_path / "malformed.db"
    conn = _create_legacy_db(db_path)
    conn.execute("INSERT INTO sessions(topic,title,note_ids,task_ids) VALUES(?,?,?,?)", ("topic-0", "bad json", "{bad", "{also-bad"))
    conn.commit()

    report = run_migrations(conn, db_path)

    assert report["task_rows"] == 1
    assert conn.execute("SELECT note_ids FROM sessions").fetchone()[0] == "{bad"
    backup = sqlite3.connect(report["backup_path"])
    assert backup.execute("SELECT note_ids, task_ids FROM sessions").fetchone() == ("{bad", "{also-bad")
    backup.close()
    conn.close()


def test_large_task_table_migrates_without_losing_rows(tmp_path):
    db_path = tmp_path / "large.db"
    conn = _create_legacy_db(db_path, task_count=750)
    task_ids = list(range(1, 751))
    conn.execute("UPDATE tasks SET topic='large'")
    conn.execute("INSERT INTO sessions(topic,title,note_ids,task_ids) VALUES(?,?,?,?)", ("large", "large", "[]", json.dumps(task_ids)))
    conn.commit()

    report = run_migrations(conn, db_path)

    assert report["task_rows"] == 750
    assert conn.execute("SELECT COUNT(*) FROM tasks_legacy_v1").fetchone()[0] == 750
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE kind='TASK_ARCHIVE'").fetchone()[0] == 750
    linked_note_ids = json.loads(conn.execute("SELECT note_ids FROM sessions").fetchone()[0])
    assert len(linked_note_ids) == 750
    assert len(set(linked_note_ids)) == 750
    conn.close()


def test_forced_failure_rolls_back_and_leaves_recoverable_backup(tmp_path, monkeypatch):
    db_path = tmp_path / "failure.db"
    conn = _create_legacy_db(db_path, task_count=20)

    def fail_archive(_conn):
        raise RuntimeError("forced archive failure")

    monkeypatch.setattr(migrations, "_archive_tasks", fail_archive)
    with pytest.raises(MigrationError, match="rolled back"):
        run_migrations(conn, db_path)

    assert _versions(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 20
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE kind='TASK_ARCHIVE'").fetchone()[0] == 0
    backups = list(tmp_path.glob("failure.db.v1*.bak"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    assert backup.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 20
    backup.close()
    conn.close()


def test_migrate_uses_selected_db_and_closes_storage(tmp_path, monkeypatch):
    selected = tmp_path / "selected.db"
    other = tmp_path / "other.db"
    for path in (selected, other):
        connection = sqlite3.connect(path)
        connection.close()
    monkeypatch.setenv("BASEMEM_DB_PATH", str(other))

    closed = []
    from storage.db import StorageManager

    storage_close = StorageManager.close

    def tracking_close(self):
        closed.append(self.db_path)
        storage_close(self)

    monkeypatch.setattr(StorageManager, "close", tracking_close)
    result = CliRunner().invoke(cli, ["--db", str(selected), "migrate"])

    assert result.exit_code == 0, result.output
    assert closed == [selected]
    selected_conn = sqlite3.connect(selected)
    other_conn = sqlite3.connect(other)
    assert _versions(selected_conn) == [1, 2]
    assert not other_conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    selected_conn.close()
    other_conn.close()
