"""Indexes a codebase into code_symbols/code_edges tables."""

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

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


CODE_DB_FILENAME = ".basemem.code.db"


def find_code_projects(search_root: str = "") -> list[dict]:
    """Scan for .basemem.code.db files and return project info."""
    import os
    if search_root:
        roots = [Path(p.strip()).resolve() for p in search_root.split(",") if p.strip()]
    else:
        home = os.path.expanduser("~")
        roots = [Path(home)]
        for extra in ["/mnt", "/media", "/opt", "/var/lib"]:
            p = Path(extra)
            if p.is_dir():
                roots.append(p)
    system_dirs = {"proc", "sys", "dev", "run", "lost+found", "boot", "lib", "lib64", "sbin", "bin"}
    results = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if (not d.startswith(".") or d == ".config") and d not in system_dirs
            ]
            if CODE_DB_FILENAME in filenames:
                db_path = Path(dirpath) / CODE_DB_FILENAME
                name = Path(dirpath).name
                try:
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                    row = conn.execute(
                        "SELECT file_count, symbol_count FROM code_projects LIMIT 1"
                    ).fetchone()
                    conn.close()
                    fc = row[0] if row else 0
                    sc = row[1] if row else 0
                except Exception:
                    fc, sc = 0, 0
                results.append({
                    "name": name,
                    "root": str(dirpath),
                    "db_path": str(db_path),
                    "files": fc,
                    "symbols": sc,
                })
    return results


class CodeIndexer:
    """Indexes source code files into a per-project .basemem.code.db."""

    def __init__(self, project_root: str):
        root = Path(project_root).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {project_root}")
        self.project_root = str(root)
        self.project_id = root.name
        self.db_path = str(root / CODE_DB_FILENAME)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        ensure_code_schema(self.conn)

    def close(self):
        self.conn.close()

    @staticmethod
    def _ensure_gitignore(project_root: str):
        gitignore = Path(project_root) / ".gitignore"
        if not gitignore.exists():
            return
        line = f"\n{CODE_DB_FILENAME}\n"
        content = gitignore.read_text()
        if CODE_DB_FILENAME not in content:
            gitignore.write_text(content.rstrip() + line)

    def index_project(
        self,
        root_path: str | None = None,
        progress_cb: Callable | None = None,
        _max_workers: int = 4,
    ):
        """Index an entire project directory."""
        root = Path(root_path or self.project_root).resolve()
        self._ensure_gitignore(str(root))
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root}")

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

        # Resolve cross-file references
        self._resolve_cross_file_references()

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
            if any(part in SKIP_DIRS for part in fp.parts):
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
            "DELETE FROM code_symbols WHERE file_path = ?",
            (file_path,),
        )
        removed = cursor.rowcount
        self.conn.execute(
            "DELETE FROM code_edges WHERE file_path = ?",
            (file_path,),
        )
        self.conn.commit()
        return {"removed": removed}

    def list_symbols(
        self, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """List all code symbols in this project's DB."""
        cur = self.conn.execute(
            """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line
               FROM code_symbols cs
               ORDER BY cs.file_path, cs.start_line
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def search_symbols(
        self, query: str, limit: int = 20, use_regex: bool = False
    ) -> list[dict]:
        """Full-text search across code symbols (name, signature, docstring, file_path, type, kind).

        Empty/trivial queries return no results (caller can fall through to browse mode).
        FTS5 syntax errors fall through to LIKE fallback.
        """
        import re

        # Empty/trivial queries -> browse mode (no results, caller falls through)
        if not query or query.strip() in (".", "*", "%"):
            return []

        if use_regex:
            try:
                pattern = re.compile(query)
            except re.error as e:
                return [{"error": f"Invalid regex: {e}"}]
            cur = self.conn.execute(
                """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                          cs.language, cs.signature, cs.start_line, cs.end_line,
                          cs.docstring, cs.kind
                   FROM code_symbols cs
                   ORDER BY cs.symbol_name"""
            )
            results: list = []
            for r in cur.fetchall():
                fields = [r["symbol_name"] or "", r["signature"] or "",
                          r["docstring"] or "", r["file_path"] or "",
                          r["symbol_type"] or "", r["kind"] or ""]
                if any(pattern.search(f) for f in fields):
                    results.append(dict(r))
                    if len(results) >= limit:
                        break
            return results

        # FTS5 with error fallback
        try:
            cur = self.conn.execute(
                """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                          cs.language, cs.signature, cs.start_line, cs.end_line,
                          cs.docstring
                   FROM code_symbols_fts fts
                   JOIN code_symbols cs ON cs.id = fts.rowid
                   WHERE code_symbols_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            )
            results = [dict(r) for r in cur.fetchall()]
            if results:
                return results
        except Exception:
            pass

        like = f"%{query.strip()}%"
        cur = self.conn.execute(
            """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring
               FROM code_symbols cs
               WHERE cs.symbol_name LIKE ? OR cs.symbol_type LIKE ? OR cs.kind LIKE ?
               ORDER BY cs.symbol_name
               LIMIT ?""",
            (like, like, like, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_symbol(self, symbol_id: int) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM code_symbols WHERE id = ?",
            (symbol_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_symbol_by_name(self, name: str, file_path: str = "") -> list[dict]:
        if file_path:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE symbol_name = ? AND file_path = ?",
                (name, file_path),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE symbol_name = ?",
                (name,),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_callers(self, symbol_name: str) -> list[dict]:
        """Find symbols that call a given symbol."""
        cur = self.conn.execute(
            """SELECT DISTINCT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line, cs.docstring,
                      ce.line_number, ce.file_path AS edge_file, ce.from_name
               FROM code_edges ce
               JOIN code_symbols cs ON cs.id = ce.from_symbol_id
               WHERE ce.edge_type = 'calls'
                 AND ce.to_name = ?
                 AND ce.from_symbol_id > 0
               LIMIT 50""",
            (symbol_name,),
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
                     AND ce.file_path = ?
                     AND cs.symbol_name = ?
                     AND ce.from_symbol_id > 0
                   LIMIT 50""",
                (file_path, symbol_name),
            )
        else:
            cur = self.conn.execute(
                """SELECT ce.*
                   FROM code_edges ce
                   JOIN code_symbols cs ON cs.id = ce.from_symbol_id
                   WHERE ce.edge_type = 'calls'
                     AND cs.symbol_name = ?
                     AND ce.from_symbol_id > 0
                   LIMIT 50""",
                (symbol_name,),
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
        ec = self.conn.execute(
            "SELECT COUNT(*) as c FROM code_edges"
        ).fetchone()
        result["edges"] = ec["c"] if ec else 0
        result["indexed"] = True
        return result

    # ── Internal ──────────────────────────────────────────────────

    def _clear_project(self):
        self.conn.execute("DELETE FROM code_symbols")
        self.conn.execute("DELETE FROM code_edges")
        self.conn.execute("DELETE FROM code_symbols_fts")
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

    def list_symbols_by_file(self, file_path: str, limit: int = 100) -> list[dict]:
        """List symbols defined in a specific file. Pass limit=0 for all results."""
        limit_sql = "" if limit <= 0 else f" LIMIT {int(limit)}"
        cur = self.conn.execute(
            f"""SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring, cs.kind
               FROM code_symbols cs
               WHERE cs.file_path = ? AND cs.project_id = ?
               ORDER BY cs.start_line
               {limit_sql}""",
            (file_path, self.project_id),
        )
        return [dict(r) for r in cur.fetchall()]

    def find_dead_code(self, limit: int = 0, language: str = "") -> list[dict]:
        """Symbols with zero incoming caller edges. Pass limit=0 for all results.
        Pass language='qml' to scan only QML, or '' to exclude dynamic-dispatch langs.
        """
        limit_sql = "" if limit <= 0 else f" LIMIT {int(limit)}"
        params: list = [self.project_id]

        if language:
            lang_filter = "AND cs.language = ?"
            params.append(language)
        else:
            lang_filter = "AND cs.language NOT IN ('bash', 'shell', 'sh', 'lua', 'qml', 'qmljs', 'js')"

        cur = self.conn.execute(
            f"""SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring, cs.kind
               FROM code_symbols cs
               LEFT JOIN code_edges ce ON ce.to_name = cs.symbol_name
                AND ce.edge_type = 'calls'
                AND ce.project_id = cs.project_id
               WHERE ce.id IS NULL
                 AND cs.project_id = ?
                 AND cs.symbol_type IN ('function', 'method')
                 {lang_filter}
                 AND cs.symbol_name NOT IN ('__init__', 'id', 'title', 'content', 'metadata', '__bool__')
                 AND cs.file_path NOT LIKE '%/cli/%'
                 AND cs.file_path NOT LIKE '%/mcp/%'
                 AND cs.file_path NOT LIKE '%/watcher.py'
                 AND cs.file_path NOT LIKE '%/server.py'
                 AND cs.file_path NOT LIKE '%/tests/%'
                 AND cs.file_path NOT LIKE 'tests/%'
               ORDER BY cs.file_path, cs.start_line
               {limit_sql}""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]

    def find_dead_exports(self, limit: int = 0) -> list[dict]:
        """Files whose symbols are never imported or called from other files.
        Converts module paths in import edges to file paths to detect cross-file references.
        Pass limit=0 for all results.
        """
        "" if limit <= 0 else f" LIMIT {int(limit)}"
        all_files = self.list_files(limit=0)

        dead_files = []
        for f in all_files:
            fp = f["file_path"]

            # Check 1: does any calls edge from another file target a symbol in this file?
            has_cross_calls = self.conn.execute(
                """SELECT 1 FROM code_edges ce
                   JOIN code_symbols cs ON ce.to_name = cs.symbol_name
                   WHERE cs.project_id = ? AND cs.file_path = ?
                     AND ce.file_path != ? AND ce.edge_type = 'calls'
                   LIMIT 1""",
                (self.project_id, fp, fp),
            ).fetchone()

            if has_cross_calls:
                continue

            # Check 2: does any import edge reference this file?
            # Convert file path to module-style: src/basemem/models.py → src.basemem.models
            module_root = fp.replace("/", ".").replace(".py", "").replace(".lua", "").replace(".js", "")
            has_imports = self.conn.execute(
                """SELECT 1 FROM code_edges
                   WHERE project_id = ? AND edge_type = 'imports'
                     AND from_name LIKE ?
                     AND file_path != ?
                   LIMIT 1""",
                (self.project_id, f"{module_root}%", fp),
            ).fetchone()

            if has_imports:
                continue

            dead_files.append(f)

        if not dead_files:
            return []

        return dead_files[:limit] if limit > 0 else dead_files

    def list_files(self, prefix: str = "", limit: int = 200) -> list[dict]:
        """List indexed files with symbol counts. Pass limit=0 for all results."""
        limit_sql = "" if limit <= 0 else f" LIMIT {int(limit)}"
        if prefix:
            cur = self.conn.execute(
                f"""SELECT file_path, COUNT(*) as symbol_count, MAX(language) as language
                   FROM code_symbols WHERE file_path LIKE ? AND project_id = ?
                   GROUP BY file_path ORDER BY file_path{limit_sql}""",
                (f"%{prefix}%", self.project_id),
            )
        else:
            cur = self.conn.execute(
                f"""SELECT file_path, COUNT(*) as symbol_count, MAX(language) as language
                   FROM code_symbols WHERE project_id = ?
                   GROUP BY file_path ORDER BY file_path{limit_sql}""",
                (self.project_id,),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_impact(self, symbol_name: str, depth: int = 2, limit: int = 50) -> list[dict]:
        """Transitive closure of symbols that depend on this one.

        Returns deduplicated list of symbols that call this symbol (directly or transitively).
        """
        results: list = []
        seen = set()
        queue = [(symbol_name, 0)]
        while queue and len(results) < limit:
            name, d = queue.pop(0)
            if d >= depth:
                continue
            callers = self.conn.execute(
                """SELECT DISTINCT cs.id, cs.symbol_name, cs.file_path, cs.symbol_type,
                          cs.start_line, ce.line_number, ce.file_path AS edge_file
                   FROM code_edges ce
                   JOIN code_symbols cs ON cs.id = ce.from_symbol_id
                   WHERE ce.edge_type = 'calls'
                     AND ce.to_name = ?
                     AND ce.from_symbol_id > 0
                     AND cs.project_id = ?
                   LIMIT 20""",
                (name, self.project_id),
            ).fetchall()
            for c in callers:
                drow = dict(c)
                key = (drow["id"], name)
                if key not in seen:
                    seen.add(key)
                    drow["via"] = name
                    results.append(drow)
                    if len(results) >= limit:
                        break
                    queue.append((drow["symbol_name"], d + 1))
        return results

    def find_references(self, symbol_name: str, limit: int = 50) -> list[dict]:
        """Find all references to a symbol across indexed files (source text search).
        Returns file:line matches, excluding the symbol's own definition lines."""
        import re
        results = []
        seen_defs = set()

        # Get definition locations to exclude them
        defs = self.conn.execute(
            "SELECT file_path, start_line FROM code_symbols WHERE symbol_name = ? AND project_id = ?",
            (symbol_name, self.project_id),
        ).fetchall()
        for d in defs:
            seen_defs.add((d["file_path"], d["start_line"]))

        pattern = re.compile(re.escape(symbol_name))
        root = Path(self.project_root)

        for f in self.list_files(limit=0):
            fp = root / f["file_path"]
            if not fp.is_file():
                continue
            try:
                with open(fp, errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if (f["file_path"], i) in seen_defs:
                            continue
                        if pattern.search(line):
                            results.append({
                                "file_path": f["file_path"],
                                "line_number": i,
                                "content": line.rstrip("\n"),
                            })
                            if len(results) >= limit:
                                return results
            except Exception:
                continue

        return results

    def sync_index(self, max_workers: int = 4) -> dict:
        """Incremental re-index: only re-index files changed since last index.

        Uses git diff (if available) or re-indexes all (fallback).
        """
        import subprocess
        repo = Path(self.project_root)
        repo / ".git"
        stats = self.get_project_stats()
        if not stats.get("indexed"):
            # No existing index — do full index
            return self.index_project(_max_workers=max_workers)

        # Try git diff to find changed files
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, cwd=self.project_root, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                changed = [line.strip() for line in result.stdout.splitlines()
                          if line.strip() and not line.startswith(".basemem")]
            else:
                changed = []
        except Exception:
            changed = []

        if not changed:
            # Also check unstaged/untracked
            try:
                result = subprocess.run(
                    ["git", "ls-files", "--other", "--modified", "--exclude-standard"],
                    capture_output=True, text=True, cwd=self.project_root, timeout=30,
                )
                if result.returncode == 0:
                    changed = [line.strip() for line in result.stdout.splitlines()
                              if line.strip() and not line.startswith(".basemem")]
            except Exception:
                pass

        if not changed:
            stat = self.get_project_stats()
            return {"status": "unchanged", "files": 0, "symbols": stat.get("symbol_count", 0), "edges": 0}

        # Re-index only changed files
        removed = 0
        added_symbols = 0
        added_edges = 0
        root = repo.resolve()
        for cf in changed:
            fp = root / cf
            if not fp.is_file():
                # File was deleted
                self.remove_file(str(cf))
                removed += 1
                continue
            # Remove old symbols for this file, then re-index
            self.remove_file(str(cf))
            try:
                sc, ec = self._index_file(str(root), str(fp))
                added_symbols += sc
                added_edges += ec
            except Exception as e:
                logger.warning(f"Failed to sync {cf}: {e}")

        if added_symbols or removed:
            self.conn.execute("INSERT INTO code_symbols_fts(code_symbols_fts) VALUES('rebuild')")
            self._resolve_cross_file_references()
            stat = self.get_project_stats()
            self.conn.execute(
                """UPDATE code_projects SET file_count = ?, symbol_count = ?, last_indexed = datetime('now')
                   WHERE id = ?""",
                (stat.get("file_count", 0), stat.get("symbol_count", 0), self.project_id),
            )
            self.conn.commit()

        return {"status": "synced", "files_changed": len(changed), "symbols_added": added_symbols, "edges_added": added_edges,
                "files_removed": removed}

    def _resolve_cross_file_references(self):
        """Post-indexing pass: resolve to_symbol_id=0 and from_symbol_id=0 edges.

        Per-file sym_id_map means cross-file calls get to_symbol_id=0.
        Uses bulk UPDATE for efficiency.
        """
        resolved = 0
        for col in ("to_symbol_id", "from_symbol_id"):
            name_col = "to_name" if col == "to_symbol_id" else "from_name"
            cur = self.conn.execute(
                f"""UPDATE code_edges SET {col} = (
                        SELECT cs.id FROM code_symbols cs
                        WHERE cs.symbol_name = code_edges.{name_col}
                          AND cs.project_id = code_edges.project_id
                        LIMIT 1
                    )
                    WHERE code_edges.{col} = 0
                      AND code_edges.project_id = ?
                      AND code_edges.{name_col} IN (
                          SELECT symbol_name FROM code_symbols
                          WHERE project_id = code_edges.project_id
                      )""",
                (self.project_id,),
            )
            resolved += cur.rowcount
        if resolved:
            self.conn.commit()
            logger.info(f"Resolved {resolved} cross-file symbol references")

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
