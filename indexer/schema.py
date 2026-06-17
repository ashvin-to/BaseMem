"""DB schema for code symbols and edges."""

CODE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS code_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL DEFAULT 'default',
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    language TEXT NOT NULL,
    kind TEXT DEFAULT '',
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_col INTEGER NOT NULL,
    end_col INTEGER NOT NULL,
    signature TEXT DEFAULT '',
    docstring TEXT DEFAULT '',
    parent_id INTEGER DEFAULT NULL,
    content_hash TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cs_project ON code_symbols(project_id);
CREATE INDEX IF NOT EXISTS idx_cs_file ON code_symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_cs_name ON code_symbols(symbol_name);
CREATE INDEX IF NOT EXISTS idx_cs_type ON code_symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_cs_parent ON code_symbols(parent_id);
CREATE INDEX IF NOT EXISTS idx_cs_lang ON code_symbols(language);

CREATE VIRTUAL TABLE IF NOT EXISTS code_symbols_fts USING fts5(
    symbol_name,
    signature,
    docstring,
    file_path,
    symbol_type,
    kind,
    content=code_symbols,
    content_rowid=id
);

CREATE TABLE IF NOT EXISTS code_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL DEFAULT 'default',
    from_symbol_id INTEGER NOT NULL DEFAULT 0,
    to_symbol_id INTEGER NOT NULL DEFAULT 0,
    from_name TEXT DEFAULT '',
    to_name TEXT DEFAULT '',
    edge_type TEXT NOT NULL,
    file_path TEXT DEFAULT '',
    line_number INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ce_from ON code_edges(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_ce_to ON code_edges(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_ce_project ON code_edges(project_id);
CREATE INDEX IF NOT EXISTS idx_ce_type ON code_edges(edge_type);

CREATE TABLE IF NOT EXISTS code_projects (
    id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    file_count INTEGER DEFAULT 0,
    symbol_count INTEGER DEFAULT 0,
    last_indexed TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def ensure_code_schema(conn):
    """Ensure all code graph tables exist, with migration support."""
    conn.executescript(CODE_SCHEMA_SQL)

    # Migration: FTS5 older versions only had 4 columns (missing symbol_type, kind)
    try:
        cols = conn.execute("PRAGMA table_info(code_symbols_fts)").fetchall()
        col_names = {r[1] for r in cols}
        missing = {"symbol_type", "kind"} - col_names
        if missing:
            fts_def = (
                "CREATE VIRTUAL TABLE code_symbols_fts USING fts5("
                "symbol_name, signature, docstring, file_path, symbol_type, kind, "
                "content=code_symbols, content_rowid=id)"
            )
            conn.execute("DROP TABLE IF EXISTS code_symbols_fts")
            conn.execute(fts_def)
            conn.execute("INSERT INTO code_symbols_fts(code_symbols_fts) VALUES('rebuild')")
    except Exception:
        pass  # pragma: no cover — first-run tables always have correct columns

    conn.commit()
