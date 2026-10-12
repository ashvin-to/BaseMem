"""DB schema for code symbols and edges."""

# Kept out of the schema script so a bulk load can drop them and rebuild once.
# Six b-trees updated per row is the bulk of the store cost on a large repo.
CODE_SYMBOL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cs_project ON code_symbols(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_cs_file ON code_symbols(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_cs_name ON code_symbols(symbol_name)",
    "CREATE INDEX IF NOT EXISTS idx_cs_type ON code_symbols(symbol_type)",
    "CREATE INDEX IF NOT EXISTS idx_cs_parent ON code_symbols(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_cs_lang ON code_symbols(language)",
]

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
    body_hash TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

{symbol_indexes}

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
    to_receiver TEXT DEFAULT '',
    edge_type TEXT NOT NULL,
    file_path TEXT DEFAULT '',
    line_number INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ce_from ON code_edges(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_ce_to ON code_edges(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_ce_project ON code_edges(project_id);
CREATE INDEX IF NOT EXISTS idx_ce_type ON code_edges(edge_type);

-- Inventory of every file the indexer has walked, including files that
-- contain zero symbols (empty __init__.py, plain .sh, config-style .js).
-- Staleness cannot be derived from code_symbols: a symbol-free file would
-- always look "new" and force a re-sync on every query.
CREATE TABLE IF NOT EXISTS code_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mtime REAL NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    symbol_count INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_cf_project ON code_files(project_id);

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


def drop_code_symbol_indexes(conn):
    """Drop the code_symbols indexes. Callers must rebuild them before returning."""
    dropped = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'code_symbols' "
        "AND sql IS NOT NULL"
    ).fetchall()
    for (name,) in dropped:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()
    return [name for (name,) in dropped]


def create_code_symbol_indexes(conn):
    """(Re)build the code_symbols indexes. Idempotent."""
    for stmt in CODE_SYMBOL_INDEXES:
        conn.execute(stmt)
    conn.commit()


def ensure_code_schema(conn):
    """Ensure all code graph tables exist, with migration support."""
    conn.executescript(CODE_SCHEMA_SQL.format(
        symbol_indexes="\n".join(s + ";" for s in CODE_SYMBOL_INDEXES) + "\n"
    ))

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

    # Migration: body_hash (name-insensitive) added after content_hash
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(code_symbols)").fetchall()}
        if "body_hash" not in cols:
            conn.execute("ALTER TABLE code_symbols ADD COLUMN body_hash TEXT DEFAULT ''")
    except Exception:
        pass

    # Migration: to_receiver added so member calls keep their object expression
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(code_edges)").fetchall()}
        if "to_receiver" not in cols:
            conn.execute("ALTER TABLE code_edges ADD COLUMN to_receiver TEXT DEFAULT ''")
    except Exception:
        pass

    conn.commit()
