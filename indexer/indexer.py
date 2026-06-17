"""Indexes a codebase into code_symbols/code_edges tables."""

import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from .parser import CodeParser
from .schema import ensure_code_schema

logger = logging.getLogger("basemem.indexer")

# Directories to skip by default
SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", "target", ".venv", "venv",
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".next",
    ".cache", "Pods", ".build", "coverage", ".tox", "eggs", "wheelhouse",
    ".mypy_cache", ".ruff_cache", ".terraform", ".serverless",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".lib", ".dll", ".dylib",
    ".exe", ".bin", ".class", ".jar", ".war",
    ".min.js", ".min.css",
    ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".log", ".lock",
}


class CodeIndexer:
    """Indexes source code files into the code graph."""

    def __init__(self, db_path: str, project_id: str = "default"):
        self.db_path = db_path
        self.project_id = project_id
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        ensure_code_schema(self.conn)

    def close(self):
        self.conn.close()

    def index_project(
        self,
        root_path: str,
        progress_cb: Optional[Callable] = None,
        max_workers: int = 4,
    ):
        """Index an entire project directory."""
        root = Path(root_path).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root_path}")

        self._clear_project()

        start = time.time()
        files = list(self._discover_files(root))
        total = len(files)
        logger.info(f"Found {total} source files in {root}")

        if progress_cb:
            progress_cb("scan", 0, total)

        indexed = 0
        all_symbols = 0
        all_edges = 0

        for f in files:
            try:
                sym_count, edge_count = self._index_file(str(root), str(f))
                indexed += 1
                all_symbols += sym_count
                all_edges += edge_count
            except Exception as e:
                logger.warning(f"Failed to index {f}: {e}")
            if progress_cb:
                progress_cb("indexing", indexed, total)

        # Rebuild FTS index
        self.conn.execute("INSERT INTO code_symbols_fts(code_symbols_fts) VALUES('rebuild')")
        self.conn.commit()

        # Update project record
        self.conn.execute(
            """INSERT OR REPLACE INTO code_projects (id, root_path, name, file_count, symbol_count, last_indexed)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (self.project_id, str(root), root.name, indexed, all_symbols),
        )
        self.conn.commit()

        elapsed = time.time() - start
        logger.info(
            f"Indexed {indexed} files, {all_symbols} symbols, {all_edges} edges "
            f"in {elapsed:.1f}s"
        )
        return {"files": indexed, "symbols": all_symbols, "edges": all_edges, "elapsed": elapsed}

    def index_files(self, root_path: str, file_paths: list[str]):
        """Index specific files (incremental update)."""
        symbols_added = 0
        edges_added = 0
        root = Path(root_path).resolve()

        for f in file_paths:
            fp = Path(f)
            if not fp.is_file():
                continue
            try:
                sym_count, edge_count = self._index_file(str(root), str(fp))
                symbols_added += sym_count
                edges_added += edge_count
            except Exception as e:
                logger.warning(f"Failed to index {f}: {e}")

        return {"symbols_added": symbols_added, "edges_added": edges_added}

    def remove_file(self, file_path: str):
        """Remove symbols for a deleted file."""
        cursor = self.conn.execute(
            "DELETE FROM code_symbols WHERE project_id = ? AND file_path = ?",
            (self.project_id, file_path),
        )
        removed = cursor.rowcount
        self.conn.execute(
            "DELETE FROM code_edges WHERE project_id = ? AND file_path = ?",
            (self.project_id, file_path),
        )
        self.conn.commit()
        return {"removed": removed}

    def search_symbols(
        self, query: str, limit: int = 20
    ) -> list[dict]:
        """Full-text search across code symbols."""
        cur = self.conn.execute(
            """SELECT cs.id, cs.project_id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring
               FROM code_symbols_fts fts
               JOIN code_symbols cs ON cs.id = fts.rowid
               WHERE code_symbols_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_symbol(self, symbol_id: int) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM code_symbols WHERE id = ? AND project_id = ?",
            (symbol_id, self.project_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_symbol_by_name(self, name: str, file_path: str = "") -> list[dict]:
        if file_path:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE project_id = ? AND symbol_name = ? AND file_path = ?",
                (self.project_id, name, file_path),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE project_id = ? AND symbol_name = ?",
                (self.project_id, name),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_callers(self, symbol_name: str) -> list[dict]:
        """Find symbols that call a given symbol."""
        cur = self.conn.execute(
            """SELECT DISTINCT cs.id, cs.project_id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line, cs.docstring,
                      ce.line_number, ce.file_path AS edge_file, ce.from_name
               FROM code_edges ce
               JOIN code_symbols cs ON cs.id = ce.from_symbol_id
               WHERE ce.edge_type = 'calls'
                 AND ce.project_id = ?
                 AND ce.to_name = ?
                 AND ce.from_symbol_id > 0
               LIMIT 50""",
            (self.project_id, symbol_name),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_callees(self, symbol_name: str, file_path: str = "") -> list[dict]:
        """Find symbols called by a given symbol."""
        if file_path:
            cur = self.conn.execute(
                """SELECT ce.*
                   FROM code_edges ce
                   JOIN code_symbols cs ON cs.id = ce.from_symbol_id
                   WHERE ce.edge_type = 'calls'
                     AND ce.project_id = ?
                     AND ce.file_path = ?
                     AND cs.symbol_name = ?
                     AND ce.from_symbol_id > 0
                   LIMIT 50""",
                (self.project_id, file_path, symbol_name),
            )
        else:
            cur = self.conn.execute(
                """SELECT ce.*
                   FROM code_edges ce
                   JOIN code_symbols cs ON cs.id = ce.from_symbol_id
                   WHERE ce.edge_type = 'calls'
                     AND ce.project_id = ?
                     AND cs.symbol_name = ?
                     AND ce.from_symbol_id > 0
                   LIMIT 50""",
                (self.project_id, symbol_name),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_project_stats(self) -> dict:
        cur = self.conn.execute(
            """SELECT file_count, symbol_count, last_indexed, name, root_path
               FROM code_projects WHERE id = ?""",
            (self.project_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"indexed": False}
        result = dict(row)
        # Count edges
        ec = self.conn.execute(
            "SELECT COUNT(*) as c FROM code_edges WHERE project_id = ?",
            (self.project_id,),
        ).fetchone()
        result["edges"] = ec["c"] if ec else 0
        result["indexed"] = True
        return result

    # ── Internal ──────────────────────────────────────────────────

    def _clear_project(self):
        self.conn.execute("DELETE FROM code_symbols WHERE project_id = ?", (self.project_id,))
        self.conn.execute("DELETE FROM code_edges WHERE project_id = ?", (self.project_id,))
        self.conn.execute("DELETE FROM code_symbols_fts WHERE rowid IN (SELECT id FROM code_symbols WHERE project_id = ?)", (self.project_id,))
        self.conn.commit()

    def _discover_files(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue
                if CodeParser.supported_extension(ext):
                    yield Path(dirpath) / fn

    def _index_file(self, root_path: str, file_path: str) -> tuple[int, int]:
        rel_path = os.path.relpath(file_path, root_path)
        parser = CodeParser.for_file(file_path)
        if parser is None:
            return 0, 0
        with open(file_path, "rb") as f:
            source_bytes = f.read()

        if not source_bytes.strip():
            return 0, 0

        symbols, edges = parser.parse(source_bytes, rel_path)
        if not symbols and not edges:
            return 0, 0

        # Batch insert symbols
        sym_id_map = {}
        for sym in symbols:
            cur = self.conn.execute(
                """INSERT INTO code_symbols
                   (project_id, file_path, symbol_name, symbol_type, language, kind,
                    start_line, end_line, start_col, end_col,
                    signature, docstring, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.project_id, sym["file_path"], sym["symbol_name"],
                    sym["symbol_type"], sym["language"], sym["kind"],
                    sym["start_line"], sym["end_line"],
                    sym["start_col"], sym["end_col"],
                    sym["signature"], sym["docstring"], sym["content_hash"],
                ),
            )
            sym_id_map[sym["symbol_name"]] = cur.lastrowid

        # Update parent references
        for sym in symbols:
            parent_name = sym.get("parent_id")
            if parent_name and parent_name in sym_id_map:
                self.conn.execute(
                    "UPDATE code_symbols SET parent_id = ? WHERE id = ? AND project_id = ?",
                    (sym_id_map[parent_name], sym_id_map[sym["symbol_name"]], self.project_id),
                )

        # Batch insert edges
        for edge in edges:
            self.conn.execute(
                """INSERT INTO code_edges
                   (project_id, from_symbol_id, to_symbol_id, from_name, to_name, edge_type, file_path, line_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.project_id,
                    sym_id_map.get(edge.get("from_name", ""), 0),
                    sym_id_map.get(edge.get("target_name", ""), 0),
                    edge.get("from_name", ""),
                    edge.get("target_name", ""),
                    edge["edge_type"],
                    edge["file_path"],
                    edge.get("line_number", 0),
                ),
            )

        self.conn.commit()
        return len(symbols), len(edges)
