"""Indexes a codebase into code_symbols/code_edges tables."""

import fnmatch
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


def _glob_segments(pat_segs, path_segs):
    """Match path segments against pattern segments, honouring `**`."""
    if not pat_segs:
        # The pattern named an ancestor directory, so it covers everything
        # beneath it. A file pattern reaching here is harmless, since a file
        # cannot contain a path.
        return True
    if not path_segs:
        return False
    head = pat_segs[0]
    rest = pat_segs[1:]
    if head == "**":
        for i in range(len(path_segs) + 1):
            if _glob_segments(rest, path_segs[i:]):
                return True
        return False
    if not fnmatch.fnmatch(path_segs[0], head):
        return False
    return _glob_segments(rest, path_segs[1:])


def _match_gitignore_pattern(pattern: str, rel: str) -> bool:
    """Whether one gitignore pattern covers a repo-relative path.

    Follows git closely enough to matter here:
      * a pattern containing `/` is anchored to the ignore file's directory
      * a pattern without `/` matches at any depth
      * `**` spans any number of path segments
      * a leading `/**` covers the whole tree
    """
    pat = pattern
    anchored = "/" in pat
    if pat.startswith("/"):
        pat = pat[1:]
        anchored = True
    if pat.startswith("**"):
        rest = pat[2:].lstrip("/")
        if not rest:
            return True  # `/**` re-includes everything beneath the root
        pat = rest
        anchored = anchored and "/" in rest
    if not pat:
        return False

    segs = rel.replace(os.sep, "/").strip("/").split("/")
    pat_segs = [s for s in pat.split("/") if s]
    if not pat_segs:
        return False
    if anchored:
        return _glob_segments(pat_segs, segs)
    # Unanchored: the pattern may match at any depth.
    for i in range(len(segs)):
        if _glob_segments(pat_segs, segs[i:]):
            return True
    return False


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
        self.project_id = root.name.lower()
        self.db_path = str(root / CODE_DB_FILENAME)
        self.conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA busy_timeout=10000;")
        self.conn.row_factory = sqlite3.Row

        # Register generated file detection heuristic for search down-ranking
        def is_generated(filepath: str) -> int:
            if not filepath:
                return 0
            import re
            patterns = [
                r'\.pb\.go$', r'\.pulsar\.go$', r'_grpc\.pb\.go$', r'_mock\.go$', r'_mocks\.go$', r'^mock_[^/]+\.go$',
                r'\.generated\.', r'\.gen\.', r'^zzz_', r'\.min\.', r'openapi_client',
            ]
            if any(re.search(p, filepath) for p in patterns):
                return 1
            if any(marker in filepath for marker in ('/generated/', '/gen/', '/mocks/', '/vendor/')):
                return 1
            return 0
        self.conn.create_function("is_generated", 1, is_generated)

        self._ignore_patterns: list[str] = []
        self._negate_patterns: list[str] = []
        # Same rules as the two lists above, in file order, so that evaluation
        # can follow git's last-match-wins instead of "any negation wins".
        self._ignore_rules: list[tuple[bool, str]] = []
        self._load_ignore_files()

        ensure_code_schema(self.conn)

    def _load_ignore_files(self):
        """Load patterns from .gitignore and .basememignore.

        `!pattern` lines are re-include rules: git applies them to undo an earlier
        ignore, so they must be matched AFTER the positive patterns rather than
        being dropped. A repo that ignores `lib/` but re-includes `bin/lib/`
        expects those files to be tracked, and to index them.

        Order is preserved in `_ignore_rules` because git's rule is last match
        wins, not "any negation beats any ignore". Splitting them into two lists
        and testing the negations first gets `lib/` + `!bin/lib/` right by
        accident, but silently deletes whole source trees otherwise: nimterop
        ships `*` then `!/**/` then `!*.*`, and testing negations first could
        not match `!/**/` against the dotless directory `nimterop`, so the bare
        `*` won and all 40 of its .nim files were pruned.
        """
        for filename in [".gitignore", ".basememignore"]:
            ignore_path = Path(self.project_root) / filename
            if ignore_path.exists():
                try:
                    for line in ignore_path.read_text().splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        negated = line.startswith('!')
                        pattern = (line[1:] if negated else line).rstrip('/')
                        if not pattern:
                            continue
                        if negated:
                            self._negate_patterns.append(pattern)
                        else:
                            self._ignore_patterns.append(pattern)
                        self._ignore_rules.append((negated, pattern))
                except Exception:
                    pass

    @staticmethod
    def _pattern_matches(rel: str, pattern: str) -> bool:
        return _match_gitignore_pattern(pattern, rel)

    def _is_skipped(self, filepath: str) -> bool:
        """Check if a file should be skipped based on SKIP_DIRS or ignore patterns.

        git's rule is last match wins, so the rules are evaluated in the order
        they appear and each one that matches overwrites the decision.
        """
        p = Path(filepath)
        if any(part in SKIP_DIRS for part in p.parts):
            return True
        try:
            rel = str(p.relative_to(self.project_root) if p.is_absolute() else p)
        except ValueError:
            return True
        if p.is_absolute() or os.sep in rel:
            rel = "/".join(Path(rel).parts)
        decision = False
        for negated, pattern in self._ignore_rules:
            if _match_gitignore_pattern(pattern, rel):
                decision = not negated
        return decision

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
        self.conn.execute(
            "DELETE FROM code_files WHERE project_id = ? AND file_path = ?",
            (self.project_id, file_path),
        )
        self.conn.commit()
        return {"removed": removed}

    def list_symbols(
        self, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """List all code symbols in this project's DB."""
        cur = self.conn.execute(
            """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.body_hash
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
                          cs.docstring, cs.kind, cs.body_hash
                   FROM code_symbols cs
                   ORDER BY is_generated(cs.file_path) ASC, cs.symbol_name"""
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

        type_filter = None
        if "type:" in query:
            match = re.search(r'type:([a-zA-Z_]+)', query)
            if match:
                type_filter = match.group(1).lower()
                query = query.replace(match.group(0), "").strip()
                if not query:
                    # If only type: was provided, fallback to LIKE with empty query
                    query = "%"

        # FTS5 with error fallback
        if type_filter is None:
            try:
                cur = self.conn.execute(
                    """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                              cs.language, cs.signature, cs.start_line, cs.end_line,
                              cs.docstring, cs.body_hash
                       FROM code_symbols_fts fts
                       JOIN code_symbols cs ON cs.id = fts.rowid
                       WHERE code_symbols_fts MATCH ?
                       ORDER BY is_generated(cs.file_path) ASC, rank
                       LIMIT ?""",
                    (query, limit),
                )
                results = [dict(r) for r in cur.fetchall()]
                if results:
                    return results
            except Exception:
                pass

        # CamelCase segment fuzzy search
        segments = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+', query)
        if len(segments) > 1 and query != "%":
            like_conditions = " AND ".join(["(cs.symbol_name LIKE ? OR cs.file_path LIKE ?)"] * len(segments))
            params = []
            for s in segments:
                params.extend([f"%{s}%", f"%{s}%"])

            type_sql = ""
            if type_filter:
                type_sql = " AND cs.symbol_type = ?"
                params.append(type_filter)

            cur = self.conn.execute(
                f"""SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                          cs.language, cs.signature, cs.start_line, cs.end_line,
                          cs.docstring, cs.body_hash
                   FROM code_symbols cs
                   WHERE {like_conditions}{type_sql}
                   ORDER BY is_generated(cs.file_path) ASC, cs.symbol_name
                   LIMIT ?""",
                params + [limit],
            )
            fuzzy_results = [dict(r) for r in cur.fetchall()]
            if fuzzy_results:
                return fuzzy_results

        like = f"%{query.strip()}%" if query != "%" else "%"

        type_sql = ""
        params_like = [like, like, like, like]
        if type_filter:
            type_sql = " AND cs.symbol_type = ?"
            params_like.append(type_filter)

        cur = self.conn.execute(
            f"""SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring, cs.body_hash
               FROM code_symbols cs
               WHERE (cs.symbol_name LIKE ? OR cs.symbol_type LIKE ? OR cs.kind LIKE ? OR cs.file_path LIKE ?){type_sql}
               ORDER BY is_generated(cs.file_path) ASC, cs.symbol_name
               LIMIT ?""",
            params_like + [limit],
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
               WHERE ce.edge_type IN ('calls', 'member_calls')
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
                   WHERE ce.edge_type IN ('calls', 'member_calls')
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
                   WHERE ce.edge_type IN ('calls', 'member_calls')
                     AND cs.symbol_name = ?
                     AND ce.from_symbol_id > 0
                   LIMIT 50""",
                (symbol_name,),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_virtual_graph_nodes(self, symbol_name: str = "", depth: int = 1, limit: int = 50) -> dict:
        """Extract virtual AST graph nodes and call/import edges normalized for GraphEngine.

        Returns:
            {"nodes": {node_id: node_dict}, "edges": [edge_dict]}
        """
        del depth
        nodes: dict = {}
        edges: list = []
        seen_edges = set()

        if symbol_name:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE symbol_name = ? AND project_id = ? LIMIT ?",
                (symbol_name, self.project_id, limit),
            )
            sym_rows = [dict(r) for r in cur.fetchall()]
            if not sym_rows:
                tokens = [t.strip() for t in symbol_name.split() if len(t.strip()) > 2]
                if tokens:
                    placeholders = " OR ".join(["symbol_name LIKE ?"] * len(tokens))
                    params = [f"%{t}%" for t in tokens]
                    cur = self.conn.execute(
                        f"SELECT * FROM code_symbols WHERE ({placeholders}) AND project_id = ? LIMIT ?",
                        params + [self.project_id, limit],
                    )
                    sym_rows = [dict(r) for r in cur.fetchall()]
        else:
            cur = self.conn.execute(
                "SELECT * FROM code_symbols WHERE project_id = ? ORDER BY is_generated(file_path) ASC, id LIMIT ?",
                (self.project_id, limit),
            )
            sym_rows = [dict(r) for r in cur.fetchall()]

        for r in sym_rows:
            node_id = f"code:{r['id']}"
            nodes[node_id] = {
                "id": node_id,
                "title": r["symbol_name"],
                "content": (
                    f"{r['symbol_type']} defined in {r['file_path']}:L{r['start_line']}-{r['end_line']}\n"
                    f"Signature: {r['signature'] or 'N/A'}\n{r['docstring'] or ''}"
                ).strip(),
                "kind": "symbol",
                "symbol_type": r["symbol_type"],
                "file_path": r["file_path"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "signature": r["signature"],
                "docstring": r["docstring"],
                "language": r["language"],
                "virtual": True,
            }

        if nodes:
            sym_names = [n["title"] for n in nodes.values() if n["title"]]
            if sym_names:
                placeholders = ",".join(["?"] * len(sym_names))
                cur = self.conn.execute(
                    f"""SELECT ce.*, cs1.id as from_id, cs2.id as to_id
                       FROM code_edges ce
                       LEFT JOIN code_symbols cs1 ON cs1.symbol_name = ce.from_name AND cs1.project_id = ce.project_id
                       LEFT JOIN code_symbols cs2 ON cs2.symbol_name = ce.to_name AND cs2.project_id = ce.project_id
                       WHERE (ce.from_name IN ({placeholders}) OR ce.to_name IN ({placeholders}))
                         AND ce.project_id = ?
                       LIMIT ?""",
                    sym_names + sym_names + [self.project_id, limit * 2],
                )
                for erow in cur.fetchall():
                    e = dict(erow)
                    from_nid = f"code:{e['from_id']}" if e.get('from_id') else f"code:{e['from_name']}"
                    to_nid = f"code:{e['to_id']}" if e.get('to_id') else f"code:{e['to_name']}"

                    if from_nid not in nodes and e.get("from_name"):
                        nodes[from_nid] = {
                            "id": from_nid,
                            "title": e["from_name"],
                            "content": f"Caller symbol from {e['file_path']}:L{e['line_number']}",
                            "kind": "symbol",
                            "symbol_type": "caller",
                            "file_path": e["file_path"],
                            "virtual": True,
                        }
                    if to_nid not in nodes and e.get("to_name"):
                        nodes[to_nid] = {
                            "id": to_nid,
                            "title": e["to_name"],
                            "content": f"Target symbol {e['to_name']}",
                            "kind": "symbol",
                            "symbol_type": "callee",
                            "file_path": e["file_path"],
                            "virtual": True,
                        }

                    edge_key = (from_nid, to_nid, e["edge_type"])
                    if edge_key not in seen_edges and from_nid in nodes and to_nid in nodes:
                        seen_edges.add(edge_key)
                        edges.append({
                            "from_id": from_nid,
                            "to_id": to_nid,
                            "edge_type": e["edge_type"],
                            "weight": 1.0,
                            "virtual": True,
                            "file_path": e["file_path"],
                            "line_number": e["line_number"],
                        })

        return {"nodes": nodes, "edges": edges}

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

    def get_index_diagnostics(self) -> dict:
        stats = self.get_project_stats()
        if not stats.get("indexed"):
            return {"status": "not_indexed", "project": self.project_root}
        languages = [
            dict(row)
            for row in self.conn.execute(
                "SELECT language, COUNT(*) AS symbols FROM code_symbols "
                "WHERE project_id = ? GROUP BY language ORDER BY symbols DESC",
                (self.project_id,),
            )
        ]
        unresolved_free = self.conn.execute(
            "SELECT COUNT(*) AS c FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'calls' AND to_symbol_id = 0",
            (self.project_id,),
        ).fetchone()
        unresolved_member = self.conn.execute(
            "SELECT COUNT(*) AS c FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'member_calls' AND to_symbol_id = 0",
            (self.project_id,),
        ).fetchone()
        edge_counts = {
            r["edge_type"]: r["c"]
            for r in self.conn.execute(
                "SELECT edge_type, COUNT(*) AS c FROM code_edges WHERE project_id = ? GROUP BY 1",
                (self.project_id,),
            )
        }
        indexed_files = self.conn.execute(
            "SELECT COUNT(DISTINCT file_path) AS c FROM code_symbols WHERE project_id = ?",
            (self.project_id,),
        ).fetchone()
        return {
            "status": "ready",
            "project": self.project_root,
            "last_indexed": stats.get("last_indexed"),
            "files": indexed_files["c"] if indexed_files else 0,
            "languages": languages,
            "unresolved_calls": unresolved_free["c"] if unresolved_free else 0,
            "unresolved_member_calls": unresolved_member["c"] if unresolved_member else 0,
            "edges": edge_counts,
        }

    # ── Internal ──────────────────────────────────────────────────

    def _clear_project(self):
        self.conn.execute("DELETE FROM code_symbols")
        self.conn.execute("DELETE FROM code_edges")
        self.conn.execute("DELETE FROM code_symbols_fts")
        self.conn.commit()

    def _discover_files(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not self._is_skipped(str(Path(dirpath) / d))]
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue
                file_path = Path(dirpath) / fn
                if not self._is_skipped(str(file_path)) and CodeParser.supported_extension(ext):
                    yield file_path

    def list_symbols_by_file(self, file_path: str, limit: int = 100) -> list[dict]:
        """List symbols defined in a specific file. Pass limit=0 for all results."""
        limit_sql = "" if limit <= 0 else f" LIMIT {int(limit)}"
        cur = self.conn.execute(
            f"""SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type,
                      cs.language, cs.signature, cs.start_line, cs.end_line,
                      cs.docstring, cs.kind, cs.body_hash
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
                      cs.docstring, cs.kind, cs.body_hash
               FROM code_symbols cs
               LEFT JOIN code_edges ce ON ce.to_name = cs.symbol_name
                AND ce.edge_type IN ('calls', 'member_calls')
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
                     AND ce.file_path != ? AND ce.edge_type IN ('calls', 'member_calls')
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
                   GROUP BY file_path ORDER BY is_generated(file_path) ASC, file_path{limit_sql}""",
                (f"%{prefix}%", self.project_id),
            )
        else:
            cur = self.conn.execute(
                f"""SELECT file_path, COUNT(*) as symbol_count, MAX(language) as language
                   FROM code_symbols WHERE project_id = ?
                   GROUP BY file_path ORDER BY is_generated(file_path) ASC, file_path{limit_sql}""",
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
                   WHERE ce.edge_type IN ('calls', 'member_calls')
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

        # 1. Precise AST Callers / Imports
        ast_refs = self.conn.execute(
            """SELECT file_path, line_number, from_name as content
               FROM code_edges
               WHERE to_name = ? AND project_id = ?
               LIMIT ?""",
            (symbol_name, self.project_id, limit)
        ).fetchall()
        for r in ast_refs:
            results.append({
                "file_path": r["file_path"],
                "line_number": r["line_number"],
                "content": f"[AST Usage] called/imported by {r['content']}",
            })
            seen_defs.add((r["file_path"], r["line_number"]))

        if len(results) >= limit:
            return results

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

    def staleness(self) -> dict:
        """Report index freshness without parsing anything.

        Compares the set of indexable files on disk against the indexed set and
        flags anything modified after the last index. Cheap enough (os.walk +
        os.stat) to run on every query, and independent of git, so it also sees
        untracked files and files git ignores but that are still indexable.
        """
        repo = Path(self.project_root)
        known = {
            r[0]: (r[1], r[2])
            for r in self.conn.execute(
                "SELECT file_path, mtime, size FROM code_files WHERE project_id = ?", (self.project_id,)
            )
        }
        on_disk: dict[str, tuple[float, int]] = {}
        for fp in self._discover_files(repo):
            try:
                st = fp.stat()
            except OSError:
                continue
            on_disk[str(fp.relative_to(repo))] = (st.st_mtime, st.st_size)

        added = sorted(set(on_disk) - set(known))
        removed = sorted(set(known) - set(on_disk))
        changed = sorted(p for p in (set(on_disk) & set(known)) if on_disk[p] != known[p])

        stats = self.get_project_stats()
        return {
            "indexed": bool(stats.get("indexed")),
            "last_indexed": stats.get("last_indexed"),
            "on_disk": len(on_disk),
            "indexed_files": len(known),
            "added": added,
            "removed": removed,
            "changed": changed,
            "stale": bool(added or removed or changed) or not stats.get("indexed"),
        }

    def resolve_refs(self, refs: list[str]) -> list[tuple[str, str, str]]:
        """Turn "path/to/file.js::SymbolName" (or a bare path) into
        (file_path, symbol_name, content_hash) tuples for memory linking.

        The content hash is captured now so a later rename can still find the
        memory: an unchanged body at a new path keeps the same hash.
        """
        out: list[tuple[str, str, str]] = []
        for raw in refs:
            ref = (raw or "").strip()
            if not ref:
                continue
            file_path, _, symbol_name = ref.partition("::")
            file_path = file_path.strip().strip("'\"")
            symbol_name = symbol_name.strip().strip("'\"")
            content_hash = ""
            if symbol_name:
                rows = self.conn.execute(
                    "SELECT COALESCE(NULLIF(body_hash, ''), content_hash) "
                    "FROM code_symbols WHERE project_id = ? AND file_path = ? AND symbol_name = ?",
                    (self.project_id, file_path, symbol_name),
                ).fetchall()
                if rows:
                    content_hash = rows[0][0] or ""
            else:
                rows = self.conn.execute(
                    "SELECT COALESCE(NULLIF(body_hash, ''), content_hash) "
                    "FROM code_symbols WHERE project_id = ? AND file_path = ? LIMIT 1",
                    (self.project_id, file_path),
                ).fetchall()
                if rows:
                    content_hash = rows[0][0] or ""
            out.append((file_path, symbol_name, content_hash))
        return out

    def symbols_with_same_body(self, content_hash: str, exclude_path: str = "") -> list[dict]:
        """Other symbols sharing a body hash — i.e. a rename or a move."""
        if not content_hash:
            return []
        rows = self.conn.execute(
            "SELECT symbol_name, file_path, start_line, language FROM code_symbols "
            "WHERE project_id = ? AND content_hash = ? AND file_path != ? LIMIT 20",
            (self.project_id, content_hash, exclude_path),
        ).fetchall()
        return [dict(r) for r in rows]

    def ensure_fresh(self, max_workers: int = 4) -> dict | None:
        """Re-index when the index has drifted. Returns a report, or None if fresh.

        Set BASEMEM_CODE_AUTO_SYNC=0 to opt out. Never raises: a failed sync must
        degrade to a stale index, never break the caller's query.
        """
        if os.environ.get("BASEMEM_CODE_AUTO_SYNC", "1").lower() in ("0", "false", "no"):
            return None
        try:
            report = self.staleness()
        except Exception as e:
            logger.warning(f"staleness check failed: {e}")
            return None
        if not report.get("stale"):
            return None
        try:
            return self.sync_index(max_workers=max_workers)
        except Exception as e:
            logger.warning(f"auto-sync failed: {e}")
            return {"status": "error", "reason": str(e)}

    def sync_index(self, max_workers: int = 4) -> dict:
        """Incremental re-index of only the files that drifted since last index."""
        report = self.staleness()
        if not report.get("indexed"):
            return self.index_project(_max_workers=max_workers)

        changed = list(report["changed"]) + list(report["added"])
        removed = list(report["removed"])

        if not changed and not removed:
            stat = self.get_project_stats()
            return {"status": "unchanged", "files": 0, "symbols": stat.get("symbol_count", 0), "edges": 0}

        root = Path(self.project_root).resolve()
        added_symbols = 0
        added_edges = 0
        for cf in changed:
            fp = root / cf
            if not fp.is_file():
                self.remove_file(str(cf))
                removed.append(cf)
                continue
            self.remove_file(str(cf))
            try:
                sc, ec = self._index_file(str(root), str(fp))
                added_symbols += sc
                added_edges += ec
            except Exception as e:
                logger.warning(f"Failed to sync {cf}: {e}")

        for cf in removed:
            self.remove_file(str(cf))

        if added_symbols or removed or changed:
            self.conn.execute("INSERT INTO code_symbols_fts(code_symbols_fts) VALUES('rebuild')")
            self._resolve_cross_file_references()
            stat = self.get_project_stats()
            self.conn.execute(
                """UPDATE code_projects SET file_count = ?, symbol_count = ?, last_indexed = datetime('now')
                   WHERE id = ?""",
                (stat.get("file_count", 0), stat.get("symbol_count", 0), self.project_id),
            )
            self.conn.commit()

        return {"status": "synced", "files_changed": len(changed), "symbols_added": added_symbols,
                "edges_added": added_edges, "files_removed": len(removed)}

    def _build_resolution_maps(self):
        """In-memory maps for scope-aware edge resolution.

        Loaded once, because the previous resolver ran a correlated subquery per
        edge. Returns (symbols_by_name, methods_by_parent, file_imports).
        """
        symbols_by_name: dict[str, list[dict]] = {}
        for row in self.conn.execute(
            "SELECT id, file_path, symbol_name, symbol_type, language FROM code_symbols "
            "WHERE project_id = ?",
            (self.project_id,),
        ):
            symbols_by_name.setdefault(row["symbol_name"], []).append(dict(row))

        methods_by_parent: dict[tuple[str, str], list[dict]] = {}
        methods_by_name: dict[str, list[dict]] = {}
        for row in self.conn.execute(
            """SELECT cs.id, cs.file_path, cs.symbol_name, cs.symbol_type, cs.language,
                      p.symbol_name AS parent
               FROM code_symbols cs JOIN code_symbols p ON cs.parent_id = p.id
               WHERE cs.project_id = ?""",
            (self.project_id,),
        ):
            rec = dict(row)
            methods_by_parent.setdefault((row["parent"], row["symbol_name"]), []).append(rec)
            methods_by_name.setdefault(row["symbol_name"], []).append(rec)

        # subclass -> [base classes], so a method lookup can walk up the chain
        bases: dict[str, list[str]] = {}
        for row in self.conn.execute(
            "SELECT from_name, to_name FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'inherits' AND from_name != '' AND to_name != ''",
            (self.project_id,),
        ):
            bases.setdefault(row["from_name"], []).append(row["to_name"])

        # file -> {variable: inferred type} from `x = Foo()` / `x = new Foo()`.
        # This is what lets `x.method()` resolve when x is a local, not a class.
        var_types: dict[str, dict[str, str]] = {}
        for row in self.conn.execute(
            "SELECT file_path, to_receiver AS variable, to_name AS type FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'instantiates' "
            "AND to_receiver IS NOT NULL AND to_receiver != '' AND to_name != ''",
            (self.project_id,),
        ):
            var_types.setdefault(row["file_path"], {})[row["variable"]] = row["type"]

        # (file, enclosing function) -> {name: declared type} for parameters and
        # method receivers. Scoped by function because different methods routinely
        # use the same receiver name for different types.
        param_types: dict[tuple[str, str], dict[str, str]] = {}
        for row in self.conn.execute(
            "SELECT file_path, from_name, to_receiver AS name, to_name AS type FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'param_type' "
            "AND to_receiver != '' AND to_name != ''",
            (self.project_id,),
        ):
            key = (row["file_path"], row["from_name"] or "")
            param_types.setdefault(key, {})[row["name"]] = row["type"]

        # file -> {local name: dotted module}. Import edges carry the imported path
        # in from_name, e.g. "storage.sessions.SessionManager".
        file_imports: dict[str, dict[str, str]] = {}
        for row in self.conn.execute(
            "SELECT DISTINCT file_path, from_name FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'imports' "
            "AND from_name IS NOT NULL AND from_name != ''",
            (self.project_id,),
        ):
            imported = row["from_name"]
            head, _, module = imported.rpartition(".")
            local = head if module else imported
            file_imports.setdefault(row["file_path"], {})[local] = module

        return (symbols_by_name, methods_by_parent, methods_by_name, file_imports,
                var_types, bases, param_types)

    def _module_to_file(self, module: str, known_files: set[str]) -> str:
        """Map a dotted module path to an indexed file, or '' when unknown."""
        if not module:
            return ""
        rel = module.replace(".", "/")
        for candidate in (
            f"{rel}.py", f"{rel}.js", f"{rel}.ts", f"{rel}.tsx", f"{rel}.rs",
            f"{rel}.go", f"{rel}.java", f"{rel}.rb", f"{rel}.php", f"{rel}.c", f"{rel}.cpp",
            f"{rel}/index.js", f"{rel}/index.ts", f"{rel}/mod.rs", f"{rel}/__init__.py",
        ):
            if candidate in known_files:
                return candidate
        stem = rel.rsplit("/", 1)[-1]
        for f in known_files:
            if Path(f).stem == stem and "/" + stem in ("/" + f, f):
                return f
            if Path(f).stem == stem:
                return f
        return ""

    def _parent_name(self, symbol_id: int) -> str:
        row = self.conn.execute(
            "SELECT p.symbol_name AS parent FROM code_symbols cs "
            "LEFT JOIN code_symbols p ON cs.parent_id = p.id WHERE cs.id = ?",
            (symbol_id,),
        ).fetchone()
        return (row["parent"] or "") if row else ""

    @staticmethod
    def _pick(candidates: list[dict]) -> int:
        """Choose one candidate, preferring definitions over references."""
        if not candidates:
            return 0
        ordered = sorted(
            candidates,
            key=lambda c: 0
            if c["symbol_type"] in ("method", "class", "interface", "struct", "function")
            else 1,
        )
        return ordered[0]["id"]

    def _method_on_class(self, class_name, name, methods_by_parent, methods_by_name, bases, depth=0):
        """Look for `name` on `class_name`, walking up its base classes.

        Without this the call graph breaks at every inheritance boundary: a method
        defined on a base class never resolves from a subclass instance.
        """
        hit = self._pick(methods_by_parent.get((class_name, name), []))
        if hit:
            return hit
        if depth >= 5:
            return 0
        for base in bases.get(class_name, ()):
            hit = self._method_on_class(base, name, methods_by_parent, methods_by_name, bases, depth + 1)
            if hit:
                return hit
        return 0

    def _resolve_member_call(self, row, imports, methods_by_parent, methods_by_name,
                              symbols_by_name, known_files, var_types, bases, param_types) -> int:
        """Resolve `receiver.name()` by looking for a method on that receiver."""
        name = row["to_name"]
        receiver = (row["to_receiver"] or "").strip()
        head = receiver.split(".")[0] if receiver else ""
        file_path = row["file_path"] or ""

        # `x = Foo()` then `x.method()`: look the method up on Foo's methods. This
        # is the common local-variable case and the main source of misses before it.
        if head:
            # A parameter or method receiver in the caller's own signature is the
            # strongest signal available; `x := New()` at file scope is the fallback.
            inferred = (param_types.get((file_path, row["from_name"] or "")) or {}).get(head) \
                or (var_types.get(file_path) or {}).get(head)
            if inferred:
                hit = self._method_on_class(inferred, name, methods_by_parent, methods_by_name, bases)
                if hit:
                    return hit
                hit = self._pick(
                    [m for m in symbols_by_name.get(name, []) if m["symbol_type"] in ("method", "function")]
                )
                if hit:
                    return hit

        if head and head in imports:
            mod_file = self._module_to_file(imports[head], known_files)
            if mod_file:
                hit = self._method_on_class(head, name, methods_by_parent, methods_by_name, bases)
                if hit:
                    return hit
                hit = self._pick(
                    [m for m in symbols_by_name.get(name, []) if m["file_path"] == mod_file]
                )
                if hit:
                    return hit

        # a class or receiver declared in this very file
        hit = self._method_on_class(head, name, methods_by_parent, methods_by_name, bases) if head else 0
        if hit:
            return hit
        if head:
            hit = self._pick([m for m in symbols_by_name.get(name, []) if m["file_path"] == file_path])
            if hit:
                return hit
        # self.foo() — the receiver is the caller's own class
        if receiver == "self" and row["from_symbol_id"]:
            parent = self._parent_name(row["from_symbol_id"])
            if parent:
                hit = self._method_on_class(parent, name, methods_by_parent, methods_by_name, bases)
                if hit:
                    return hit
        # a method of the enclosing symbol
        if row["from_name"]:
            hit = self._method_on_class(row["from_name"], name, methods_by_parent, methods_by_name, bases)
            if hit:
                return hit
        # last resort: exactly one class in the project owns a method of this name.
        # Ambiguous names stay unresolved rather than being linked to a random owner.
        owners = methods_by_name.get(name, [])
        if len(owners) == 1:
            return owners[0]["id"]
        return 0

    def _resolve_free_call(self, row, imports, symbols_by_name, known_files) -> int:
        """Resolve a bare `name()` through local scope, imports, then the project."""
        name = row["to_name"]
        file_path = row["file_path"] or ""

        hit = self._pick([m for m in symbols_by_name.get(name, []) if m["file_path"] == file_path])
        if hit:
            return hit

        if name in imports:
            mod_file = self._module_to_file(imports[name], known_files)
            if mod_file:
                hit = self._pick([m for m in symbols_by_name.get(name, []) if m["file_path"] == mod_file])
                if hit:
                    return hit

        return self._pick(symbols_by_name.get(name, []))

    def _resolve_cross_file_references(self):
        """Resolve edges whose target is currently only a name string.

        Resolution is scope-aware: a member call is looked for on its receiver, and
        a free call is looked for in the same file, then through an import, then
        project-wide. Whatever stays unresolved is a genuinely external or dynamic
        call, which is a real answer rather than a gap to hide.
        """
        (symbols_by_name, methods_by_parent, methods_by_name, file_imports,
         var_types, bases, param_types) = self._build_resolution_maps()
        known_files = {f["file_path"] for rows in symbols_by_name.values() for f in rows}

        rows = self.conn.execute(
            "SELECT id, file_path, from_name, to_name, to_receiver, edge_type, from_symbol_id "
            "FROM code_edges WHERE project_id = ? AND coalesce(to_symbol_id, 0) = 0 "
            "AND to_name IS NOT NULL AND to_name != ''",
            (self.project_id,),
        ).fetchall()

        updates: list[tuple[int, int]] = []
        source_ids: dict[int, int] = {}
        for r in rows:
            source_ids[r["id"]] = r["from_symbol_id"] or 0
            imports = file_imports.get(r["file_path"] or "", {})
            if r["edge_type"] == "member_calls":
                target = self._resolve_member_call(
                    r, imports, methods_by_parent, methods_by_name, symbols_by_name,
                    known_files, var_types, bases, param_types
                )
            else:
                target = self._resolve_free_call(r, imports, symbols_by_name, known_files)
            if target:
                updates.append((target, r["id"]))

        # An edge never points at its own source. Resolving a base or callee by name
        # inside a repo with duplicate names happily lands on the caller itself, and
        # a self-call or a D->D inheritance is always wrong.
        updates = [
            (tid, eid)
            for tid, eid in updates
            if tid != (source_ids.get(eid) or 0)
        ]
        if updates:
            self.conn.executemany("UPDATE code_edges SET to_symbol_id = ? WHERE id = ?", updates)
            self.conn.commit()
            logger.info(f"Resolved {len(updates)} cross-file symbol references")

    def _record_file(self, rel_path: str, file_path: str, symbol_count: int) -> None:
        """Track a walked file in the inventory, even when it has no symbols."""
        try:
            st = os.stat(file_path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            return
        self.conn.execute(
            """INSERT INTO code_files (project_id, file_path, mtime, size, symbol_count, indexed_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(project_id, file_path) DO UPDATE SET
                   mtime = excluded.mtime, size = excluded.size,
                   symbol_count = excluded.symbol_count, indexed_at = excluded.indexed_at""",
            (self.project_id, rel_path, mtime, size, symbol_count),
        )

    def _index_file(self, root_path: str, file_path: str) -> tuple[int, int]:
        rel_path = os.path.relpath(file_path, root_path)
        parser = CodeParser.for_file(file_path)
        if parser is None:
            return 0, 0
        with open(file_path, "rb") as f:
            source_bytes = f.read()

        if not source_bytes.strip():
            self._record_file(rel_path, file_path, 0)
            return 0, 0

        symbols, edges = parser.parse(source_bytes, rel_path)
        if not symbols and not edges:
            self._record_file(rel_path, file_path, 0)
            return 0, 0

        # Batch insert symbols
        sym_id_map = {}
        for sym in symbols:
            cur = self.conn.execute(
                """INSERT INTO code_symbols
                   (project_id, file_path, symbol_name, symbol_type, language, kind,
                    start_line, end_line, start_col, end_col,
                    signature, docstring, content_hash, body_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.project_id, sym["file_path"], sym["symbol_name"],
                    sym["symbol_type"], sym["language"], sym["kind"],
                    sym["start_line"], sym["end_line"],
                    sym["start_col"], sym["end_col"],
                    sym["signature"], sym["docstring"], sym["content_hash"],
                    sym.get("body_hash", ""),
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
            # Same invariant as the cross-file pass: an edge never points at its own
            # source. Same-file resolution by name happily lands on the caller.
            from_id = sym_id_map.get(edge.get("from_name", ""), 0)
            to_id = sym_id_map.get(edge.get("target_name", ""), 0)
            if to_id and to_id == from_id:
                to_id = 0
            self.conn.execute(
                """INSERT INTO code_edges
                   (project_id, from_symbol_id, to_symbol_id, from_name, to_name,
                    to_receiver, edge_type, file_path, line_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.project_id,
                    from_id,
                    to_id,
                    edge.get("from_name", ""),
                    edge.get("target_name", ""),
                    edge.get("target_receiver", ""),
                    edge["edge_type"],
                    edge["file_path"],
                    edge.get("line_number", 0),
                ),
            )

        self.conn.commit()
        self._record_file(rel_path, file_path, len(symbols))
        return len(symbols), len(edges)
