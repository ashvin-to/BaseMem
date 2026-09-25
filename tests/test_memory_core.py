import sqlite3

from storage.db import StorageManager
from storage.sessions import SessionManager, _ensure_schema


def test_metadata_crud_and_supersession_filter(tmp_path):
    manager = SessionManager(StorageManager(str(tmp_path / "core.db")))
    first = manager.create_note("p", "DECISION", "Use SQLite", importance=2, confidence=-1, provenance={"source": "test"})
    second = manager.create_note("p", "DECISION", "Do not use SQLite", scope="storage", importance=0.9)
    assert manager.get_note(first["id"])["importance"] == 1.0
    assert manager.get_note(first["id"])["confidence"] == 0.0
    manager.update_note(first["id"], status="superseded", superseded_by=int(second["id"].split("-")[1]))
    assert [n["id"] for n in manager.list_notes("p")] == [int(second["id"].split("-")[1])]
    assert len(manager.list_notes("p", include_superseded=True)) == 2


def test_extraction_separates_modal_hypothesis_and_decision(tmp_path):
    manager = SessionManager(StorageManager(str(tmp_path / "extract.db")))
    result = manager.auto_extract_memories("p", "We should ship.\nIt might work.")
    assert [item["type"] for item in result] == ["decision", "hypothesis"]
    assert result[0]["note_id"] != result[1]["note_id"]


def test_retrieval_is_explainable_and_logs_access(tmp_path):
    manager = SessionManager(StorageManager(str(tmp_path / "search.db")))
    manager.create_note("p", "FACT", "SQLite stores durable memory", importance=0.8, confidence=0.9)
    result = manager.rank_memories("p", "SQLite memory", historical=True)
    assert set(result[0]["score_components"]) == {"fts", "metadata", "graph", "temporal", "supersession"}
    assert manager.storage.connection.execute("SELECT COUNT(*) FROM memory_access_log").fetchone()[0] == 1


def test_legacy_tasks_archive_idempotently(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE tasks(id INTEGER PRIMARY KEY, topic TEXT, title TEXT, status TEXT, priority TEXT, depends_on TEXT, files TEXT, notes TEXT, created_at TEXT, completed_at TEXT);
    INSERT INTO tasks VALUES(1, 'p', 'Ship core', 'done', 'high', '[]', '["core.py"]', '[]', '2024-01-01', '2024-01-02');
    """)
    conn.commit()
    _ensure_schema(conn)
    _ensure_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM tasks_legacy_v1").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE kind='task_archive'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=1").fetchone()[0] == 1
