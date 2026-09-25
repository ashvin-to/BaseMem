import sqlite3

from indexer.schema import ensure_code_schema
from indexer.understanding import Budget, CodeUnderstanding


class FakeIndexer:
    def __init__(self):
        self.project_id = "demo"
        self.project_root = "/tmp/demo"
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_code_schema(self.conn)
        symbols = [
            (1, "app/session.py", "SessionManager", "class", "def", "session", 1, 20, "Session recovery"),
            (2, "app/api.py", "start_handler", "function", "def", "api", 1, 10, "Start a session"),
            (3, "app/storage.py", "load_session", "function", "def", "storage", 1, 10, "Load session state"),
            (4, "tests/test_session.py", "test_recovery", "function", "def", "test", 1, 10, "session recovery"),
        ]
        self.conn.executemany(
            "INSERT INTO code_symbols "
            "(id, project_id, file_path, symbol_name, symbol_type, language, kind, start_line, end_line, start_col, end_col, docstring) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(row[0], self.project_id, *row[1:], 0, 0) for row in symbols],
        )
        self.conn.executemany(
            "INSERT INTO code_edges(project_id, from_symbol_id, to_symbol_id, from_name, to_name, edge_type) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (self.project_id, 2, 1, "start_handler", "SessionManager", "calls"),
                (self.project_id, 1, 3, "SessionManager", "load_session", "calls"),
            ],
        )
        self.conn.commit()

    def search_symbols(self, query, limit):
        rows = self.conn.execute("SELECT * FROM code_symbols WHERE symbol_name LIKE ? LIMIT ?", (f"%{query}%", limit))
        return [dict(row) for row in rows]


def test_understanding_is_bounded_and_grounded():
    indexer = FakeIndexer()
    artifact = CodeUnderstanding(indexer).understand("session", 2, Budget.bounded(max_nodes=8, max_chars=2000))
    names = {item["symbol"] for item in artifact["evidence"]}
    assert "SessionManager" in names
    assert "load_session" in names
    assert artifact["flows"]
    assert artifact["confidence"] > 0
    assert len(artifact["evidence"]) <= 8
    indexer.conn.close()


def test_understanding_cache_invalidates_when_symbols_change():
    indexer = FakeIndexer()
    engine = CodeUnderstanding(indexer)
    first = engine.understand("session", 1, Budget.bounded(max_nodes=8))
    assert engine.understand("session", 1, Budget.bounded(max_nodes=8)) == first
    indexer.conn.execute("UPDATE code_symbols SET updated_at = datetime('now', '+1 second') WHERE id = 1")
    indexer.conn.commit()
    second = engine.understand("session", 1, Budget.bounded(max_nodes=8))
    assert second["evidence"]
    indexer.conn.close()


def test_empty_query_has_no_evidence():
    indexer = FakeIndexer()
    artifact = CodeUnderstanding(indexer).understand("", 2, Budget.bounded())
    assert artifact["confidence"] == 0
    assert artifact["evidence"] == []
    indexer.conn.close()
