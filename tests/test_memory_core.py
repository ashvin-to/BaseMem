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
    assert set(result[0]["score_components"]) >= {
        "fts_score",
        "importance_score",
        "confidence_score",
        "graph_score",
        "temporal_score",
        "supersession_score",
        "final_score",
    }
    assert manager.storage.connection.execute("SELECT COUNT(*) FROM memory_access_log").fetchone()[0] == 1


def test_context_compiler_respects_current_historical_and_budget_rules(tmp_path):
    manager = SessionManager(StorageManager(str(tmp_path / "context.db")))
    old = manager.create_note("p", "DECISION", "We use Redis for sessions", importance=0.8)
    current = manager.create_note("p", "DECISION", "We use PostgreSQL for sessions", importance=0.9)
    manager.update_note(old["id"], status="superseded", superseded_by=int(current["id"].split("-")[1]))
    current_context = manager.compile_context("p", "Which database do we use?", token_budget=80)
    current_text = str(current_context["sections"])
    assert "PostgreSQL" in current_text
    assert "Redis" not in current_text
    historical = manager.compile_context("p", "Which database did we previously use?", token_budget=80)
    assert "Redis" in str(historical["sections"])
    assert historical["token_count"] <= 80
    assert manager.compile_context("p", "unrelated deployment question", token_budget=20)["sections"] == {}


def test_session_to_session_context_round_trip(tmp_path):
    manager = SessionManager(StorageManager(str(tmp_path / "session.db")))
    manager.update_planet("p", "p", goal="reliable memory")
    first = manager.create_session("p", "architecture", "agent-a")
    manager.add_note("", "p", "DECISION", "Use SQLite WAL for durable local memory", agent_id="agent-a", importance=0.95)
    manager.close_session(first, "Chose SQLite WAL")
    manager.create_session("p", "later", "agent-b")
    context = manager.build_agent_context("p", query="Which database did we choose?", result_limit=5)
    assert "SQLite WAL" in context
    assert "Chose SQLite WAL" in context

    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE tasks(
        id INTEGER PRIMARY KEY, topic TEXT, title TEXT, status TEXT, priority TEXT,
        depends_on TEXT, files TEXT, notes TEXT, created_at TEXT, completed_at TEXT
    );
    INSERT INTO tasks VALUES(1, 'p', 'Ship core', 'done', 'high', '[]', '["core.py"]', '[]', '2024-01-01', '2024-01-02');
    CREATE TABLE sessions(
        id INTEGER PRIMARY KEY, topic TEXT, title TEXT, status TEXT, started_at TEXT,
        ended_at TEXT, last_active_at TEXT, summary TEXT, agent_id TEXT, note_ids TEXT, task_ids TEXT
    );
    INSERT INTO sessions VALUES(1, 'p', 'Old session', 'closed', '2024-01-01', '2024-01-02', '2024-01-02', NULL, 'legacy', '[2]', '[1]');
    """)
    conn.commit()
    _ensure_schema(conn)
    _ensure_schema(conn)
    note = conn.execute("SELECT id, content, provenance FROM notes WHERE UPPER(kind)='TASK_ARCHIVE'").fetchone()
    assert note is not None
    assert "Task ID: 1" in note[1]
    assert '"task_id": 1' in note[2]
    assert conn.execute("SELECT note_ids FROM sessions WHERE id=1").fetchone()[0] == "[2, 1]"
    assert "task_ids" not in {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert conn.execute("SELECT COUNT(*) FROM tasks_legacy_v1").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_fresh_schema_migrations_are_idempotent(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    conn.execute(
        """CREATE TABLE notes (
            id INTEGER PRIMARY KEY, topic TEXT NOT NULL, kind TEXT NOT NULL,
            content TEXT NOT NULL, title TEXT, agent_id TEXT, status TEXT,
            created_at TEXT, updated_at TEXT, importance REAL DEFAULT 0.5,
            confidence REAL DEFAULT 0.5
        )"""
    )
    conn.commit()
    _ensure_schema(conn)
    _ensure_schema(conn)
    notes_columns = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"importance", "confidence", "provenance"} <= notes_columns
    assert "note_ids" in session_columns
    assert "task_ids" not in session_columns
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
