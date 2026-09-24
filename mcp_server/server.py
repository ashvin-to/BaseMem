"""MCP server for BaseMem."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    """Resolve DB path and ensure schema exists."""
    path = _resolve_db_path()
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    from storage.sessions import _ensure_schema as _ensure_all_schema
    conn = sqlite3.connect(path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    try:
        _ensure_all_schema(conn)
    finally:
        conn.close()
    return path


def _resolve_db_path() -> str:
    """Resolve DB path without side effects."""
    from_env = _env_path()
    return from_env or str(BASE_DIR / "basemem.db")


def _env_path() -> "str | None":
    import os

    raw = os.environ.get("BASEMEM_DB_PATH")
    if raw:
        return raw

    home = os.environ.get("HOME", "/tmp")

    # Match CLI/Flask default location
    legacy = os.path.join(home, ".basemem", "basemem.db")
    if os.path.isfile(legacy):
        return legacy

    data_dir = os.environ.get("XDG_DATA_HOME") or os.path.join(
        home, ".local", "share"
    )
    candidate = os.path.join(data_dir, "basemem", "basemem.db")
    if os.path.isfile(candidate):
        return candidate
    return None


import json
import os
import sqlite3
from functools import wraps

from mcp.server.fastmcp import FastMCP

def _get_initial_instructions() -> "str | None":
    return (
        "BaseMem memory + code intelligence. "
        "When the user asks about code, a bug, or exploring the repo: call code_find FIRST "
        "(grep=True for text search; empty result means call code_init(projectRoot) once, then retry). "
        "Read code with code_read(filePath, offset, limit<=50); trace callers with code_explore; "
        "list files with code_files; review diffs with get_review_context(files). "
        "Context is auto-injected at session start — do NOT call getContext then; call it only to refresh or switch topics. "
        "When you make a decision, fix, or learn a fact: call logInteraction(topic, decision=...) immediately. "
        "End sessions with logInteraction(topic, summary=..., activity=\"done\"). Topic = repo folder name."
    )


server = FastMCP("mem", instructions=_get_initial_instructions())


def _optional_tool(*args, **kwargs):
    """Decorator that only registers the tool if BASEMEM_ENABLE_ADVANCED_TOOLS=1/true.
    These tools (compute_similarity, rerank, set_memory_state, get_node, code_list_projects)
    are useful for curation and discovery but not needed mid-conversation.
    They add noise to the tool list. Enable only when actively curating or debugging."""
    val = os.environ.get("BASEMEM_ENABLE_ADVANCED_TOOLS", "")
    if val in ("1", "true", "True"):
        return server.tool(*args, **kwargs)
    return lambda f: f




@server.tool(description="Index project code (tree-sitter). Auto-runs on first code_find.")
def code_init(projectRoot: str) -> str:
    import os
    if not os.path.isdir(projectRoot):
        return f"Directory not found: {projectRoot}"

    from indexer import CodeIndexer
    indexer = CodeIndexer(projectRoot)
    try:
        result = indexer.index_project(_max_workers=4)
        return (
            f"code_init ok files={result['files']} symbols={result['symbols']} "
            f"edges={result['edges']} elapsed={result['elapsed']:.1f}s"
        )
    finally:
        indexer.close()


def _detect_project_root() -> str:
    """Walk up from CWD to find a project root with .basemem.code.db."""
    import os

    from indexer import CODE_DB_FILENAME
    cwd = os.getcwd()
    parent = cwd
    while True:
        if os.path.isdir(os.path.join(parent, ".git")) or os.path.isfile(os.path.join(parent, CODE_DB_FILENAME)):
            return parent
        new_parent = os.path.dirname(parent)
        if new_parent == parent:
            return cwd
        parent = new_parent


def _fmt_loc(file_path: str) -> str:
    """Short file path: strip common prefixes, keep last 3 parts."""
    path = file_path.replace("\\", "/")
    for prefix in ("src/basemem/", "basemem/"):
        if path.startswith(prefix):
            path = path.removeprefix(prefix)
            break
    parts = path.split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else path


_MAX_CODE_LINES = 50


def _bounded_limit(limit: int) -> int:
    if limit <= 0:
        return _MAX_CODE_LINES
    return min(limit, _MAX_CODE_LINES)


def _ensure_code_index(project_root: str):
    from indexer.lifecycle import open_or_create_index

    return open_or_create_index(project_root, max_workers=4)


def _grouped_text_query(query: str) -> str:
    import re

    terms = [re.escape(term) for term in query.split() if len(term) > 1]
    return r"\b(?:" + "|".join(terms) + r")\b" if len(terms) > 1 else query


def _rg_text_search(root: str, query: str, file_path: str, use_regex: bool, context: int):
    import subprocess

    cmd = ["rg", "-n", "--no-heading", "--color", "never"]
    if context > 0:
        cmd.extend(["-C", str(context)])
    if file_path:
        cmd.extend(["--glob", file_path])
    if use_regex:
        cmd.extend(["--regexp", query])
    else:
        cmd.extend(["--fixed-strings", query])
    cmd.append(root)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


@server.tool(description="STEP 1 for any code question or exploration. Returns compact symbol/text locations first; use code_read for source. grep=True searches text; useRegex=True requires grep=True. Results are bounded to 50 entries.")
def code_find(
    query: str = "",
    projectRoot: str = "",
    limit: int = 10,
    useRegex: bool = False,
    dead: bool = False,
    filePath: str = "",
    source: bool = False,
    references: bool = False,
    grep: bool = False,
    path: str = "",
    context: int = 0,
) -> str:
    import os
    import subprocess

    if not filePath and path:
        filePath = path

    requested_limit = limit
    limit = _bounded_limit(limit)

    if grep and query:
        root = projectRoot or _detect_project_root() or "."
        try:
            search_query = query if useRegex else _grouped_text_query(query)
            result = _rg_text_search(root, search_query, filePath, useRegex or " " in query, max(0, context))
            if result.returncode not in (0, 1):
                return f"code_find: grep error: {result.stderr.strip()}"
            if not result.stdout.strip():
                return f"code_find: no matches: {query}"
            lines = result.stdout.strip().splitlines()
            shown = lines[:limit]
            root_prefix = os.path.abspath(root).rstrip(os.sep) + os.sep
            parts = [f"code_find text={len(lines)} shown={len(shown)} query={query!r}"]
            for line in shown:
                parts.append(line.replace(root_prefix, ""))
            if len(lines) > limit:
                parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow filePath/query")
            if requested_limit > _MAX_CODE_LINES:
                parts.append(f"capped: requested {requested_limit}, returned {limit}")
            return "\n".join(parts)
        except FileNotFoundError:
            return "code_find: ripgrep (rg) not found; retry without grep=True"
        except subprocess.TimeoutExpired:
            return f"code_find: search timed out: {query}"

    from indexer import CODE_DB_FILENAME, CodeIndexer
    if not projectRoot:
        projectRoot = _detect_project_root()
    if not os.path.isdir(projectRoot):
        return f"Directory not found: {projectRoot}"
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        try:
            _ci = CodeIndexer(projectRoot)
        except ValueError as e:
            return str(e)
        try:
            _ci.index_project(_max_workers=4)
        finally:
            _ci.close()
    indexer = CodeIndexer(projectRoot)
    try:
        # Dead code mode (import-chain analysis)
        if dead:
            results = indexer.find_dead_exports(limit=0)
            if not results:
                return "All files are reachable via imports."
            parts = [f"{len(results)} file(s) never imported by other files:"]
            for r in results:
                parts.append(f"  {r['file_path']} ({r['symbol_count']} symbols)")
            return "\n".join(parts)

        # References mode — find all occurrences across indexed files
        if references and query:
            refs = indexer.find_references(query, limit=limit)
            if not refs:
                # Fall back to ripgrep text search for cross-package references
                # that the indexer's cross-file resolution may have missed
                try:
                    import subprocess as _rg
                    cmd = ["rg", "-n", "--no-heading", "--fixed-strings", query, projectRoot]
                    rg_result = _rg.run(cmd, capture_output=True, text=True, timeout=30)
                    if rg_result.returncode in (0, 1) and rg_result.stdout.strip():
                        rg_lines = rg_result.stdout.strip().splitlines()[:limit]
                        parts = [f"{len(rg_lines)} text match(es) to '{query}' (indexer fallback):"]
                        for line in rg_lines:
                            parts.append(f"  {line}")
                        if len(rg_lines) >= limit:
                            parts.append(f"  ... and more")
                        return "\n".join(parts)
                except FileNotFoundError:
                    pass
                except _rg.TimeoutExpired:
                    pass
                return f"No references to '{query}' found."
            parts = [f"{len(refs)} reference(s) to '{query}':"]
            for r in refs:
                parts.append(f"  {r['file_path']}:{r['line_number']}: {r['content']}")
            return "\n".join(parts)

        # File-level browse mode
        if filePath and (not query or query.strip() in (".", "*", "%", "")):
            results = indexer.list_symbols_by_file(filePath, limit=limit)
            if not results:
                return f"No symbols in '{filePath}'."
            parts = [f"{len(results)} symbol(s) in {filePath}:"]
            for r in results:
                sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                parts.append(f"  [{r['id']}] {r['symbol_name']} ({r['symbol_type'][:4]}){sig}")
            return "\n".join(parts)

        sym = None
        try:
            sid = int(query)
            sym = indexer.get_symbol(sid)
        except ValueError:
            pass

        if not sym:
            symbols = indexer.get_symbol_by_name(query)
            if len(symbols) == 1:
                sym = symbols[0]
            elif len(symbols) > 1:
                # Apply file filter
                if filePath:
                    symbols = [s for s in symbols if s['file_path'] == filePath]
                    if len(symbols) == 1:
                        sym = symbols[0]
                if not sym:
                    parts = [f"Multiple '{query}':"]
                    for s in symbols:
                        loc = _fmt_loc(s['file_path'])
                        sig = f" {s['signature'][:60]}" if s.get('signature') else ""
                        parts.append(f"  [{s['id']}] {s['symbol_name']} ({loc}){sig}")
                    return "\n".join(parts)

        if sym:
            callers = indexer.get_callers(sym['symbol_name'])
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            loc = _fmt_loc(sym['file_path'])
            start_line = sym.get('start_line') or 1
            end_line = sym.get('end_line') or start_line
            parts = [f"code_find symbol id={sym['id']} {sym['symbol_name']} {loc}:{start_line}-{end_line} lang={sym['language']}"]
            if sym.get('signature'):
                parts.append(f"signature: {sym['signature']}")
            if sym.get('docstring'):
                parts.append(f"doc: {sym['docstring'][:200]}")
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10])
                parts.append(f"callers: {cstr}")
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
                parts.append(f"calls: {cstr}")
            if source:
                abs_fp = os.path.join(projectRoot, sym['file_path'])
                if os.path.isfile(abs_fp):
                    with open(abs_fp) as _f:
                        lines = _f.read().splitlines()
                    start = max(0, start_line - 1)
                    end = min(len(lines), end_line, start + _MAX_CODE_LINES)
                    parts.append(f"source: {sym['file_path']}:{start + 1}-{end}")
                    for i in range(start, end):
                        parts.append(lines[i])
                    if end < end_line:
                        parts.append(f"more: code_read(filePath={sym['file_path']!r}, offset={end + 1}, limit={_MAX_CODE_LINES})")
            else:
                parts.append(f"read: code_read(filePath={sym['file_path']!r}, offset={start_line}, limit=50)")
            return "\n".join(parts)

        results = indexer.search_symbols(query, limit=limit, use_regex=useRegex)
        if filePath:
            results = [r for r in results if r['file_path'] == filePath]
        if results:
            parts = [f"{len(results)} match(es):"]
            for r in results:
                loc = _fmt_loc(r['file_path'])
                sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                parts.append(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
            return "\n".join(parts)

        # Partial-match fallback: LIKE '%query%' on symbol_name (case-insensitive)
        if not grep and query and query.strip() not in (".", "*", "%", ""):
            try:
                partial_cur = indexer.conn.execute(
                    """SELECT id, file_path, symbol_name, symbol_type,
                              language, signature, start_line, end_line, docstring
                       FROM code_symbols
                       WHERE LOWER(symbol_name) LIKE LOWER(?)
                       ORDER BY symbol_name
                       LIMIT ?""",
                    (f"%{query}%", limit),
                )
                partial_results = [dict(r) for r in partial_cur.fetchall()]
                if filePath:
                    partial_results = [r for r in partial_results if r['file_path'] == filePath]
                if partial_results:
                    parts = [f"No exact match for '{query}'. Showing partial matches:"]
                    for r in partial_results:
                        loc = _fmt_loc(r['file_path'])
                        sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                        parts.append(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
                    return "\n".join(parts)
            except Exception:
                pass

        # Automatic text search fallback — when symbol search fails, try ripgrep
        # to find the query in file contents (like grep -n). This handles
        # natural language queries, config files, and cross-package refs.
        if not grep and query and query.strip() not in (".", "*", "%", ""):
            try:
                rg_result = _rg_text_search(projectRoot, query, filePath, useRegex, max(0, context))
                if rg_result.returncode in (0, 1) and rg_result.stdout.strip():
                    rg_lines = rg_result.stdout.strip().splitlines()
                    shown = rg_lines[:limit]
                    root_prefix = os.path.abspath(projectRoot).rstrip(os.sep) + os.sep
                    parts = [f"code_find text={len(rg_lines)} shown={len(shown)} query={query!r} fallback=true"]
                    for line in shown:
                        parts.append(line.replace(root_prefix, ""))
                    if len(rg_lines) > limit:
                        parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow filePath/query")
                    return "\n".join(parts)
            except FileNotFoundError:
                pass
            except subprocess.TimeoutExpired:
                pass

        _c = indexer.conn
        total = _c.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0]
        files = _c.execute("SELECT COUNT(DISTINCT file_path) FROM code_symbols").fetchone()[0]
        parts = [f"code_find no_match query={query!r} files={files} symbols={total}"]
        rows = _c.execute("""
            SELECT file_path, COUNT(*) as cnt
            FROM code_symbols GROUP BY file_path ORDER BY file_path LIMIT ?
        """, (limit,)).fetchall()
        for row in rows:
            if filePath and row['file_path'] != filePath:
                continue
            parts.append(f"file: {row['file_path']} symbols={row['cnt']}")
        if files > limit:
            parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow filePath")
        return "\n".join(parts)
    finally:
        indexer.close()


@_optional_tool(description="Trace call chain: who calls this symbol and what does it call?")
def code_trace(
    symbolName: str,
    projectRoot: str = "",
    direction: str = "both",
    depth: int = 2,
    limit: int = 10,
) -> str:
    import os

    from indexer import CODE_DB_FILENAME, CodeIndexer
    if not projectRoot:
        projectRoot = _detect_project_root()
    limit = _bounded_limit(limit)
    if not os.path.isdir(projectRoot):
        return f"No code index at {projectRoot}."
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        indexer = _ensure_code_index(projectRoot)
    else:
        indexer = CodeIndexer(projectRoot)
    try:
        lines = []
        seen = set()

        def _trace(name: str, d: int, prefix: str = ""):
            if d > depth or name in seen:
                return
            seen.add(name)
            if direction in ("inbound", "both"):
                callers = indexer.get_callers(name)
                if callers:
                    for c in callers[:limit]:
                        loc = _fmt_loc(c['file_path'])
                        lines.append(f"{prefix}inbound {c['symbol_name']} {loc}:{c['line_number']}")
                        _trace(c['symbol_name'], d + 1, prefix + "    ")
            if direction in ("outbound", "both"):
                callees = indexer.get_callees(name)
                if callees:
                    for c in callees[:limit]:
                        loc = _fmt_loc(c['file_path'])
                        lines.append(f"{prefix}outbound {c['to_name']} {loc}:{c['line_number']}")
                        _trace(c['to_name'], d + 1, prefix + "    ")

        lines.insert(0, f"code_trace symbol={symbolName!r} direction={direction} depth={depth} limit={limit}")
        _trace(symbolName, 1)
        if len(lines) <= 1:
            return f"code_trace: no call chain for {symbolName!r}"
        return "\n".join(lines)
    finally:
        indexer.close()


@_optional_tool(description="Scan for indexed code projects.")
def code_list_projects(searchRoot: str = "") -> str:
    """Scan for all .basemem.code.db files on the system."""
    from indexer.indexer import find_code_projects
    projects = find_code_projects(searchRoot)
    if not projects:
        return "No projects found."
    parts = [f"{len(projects)} project(s):"]
    for p in sorted(projects, key=lambda x: x["name"]):
        parts.append(f"  {p['name']}: {p['symbols']}s {p['files']}f")
    return "\n".join(parts)


@server.tool(description="List files or glob paths. Returns compact file paths with counts, shown/total metadata, and a continuation hint; auto-indexes if needed.")
def code_files(projectRoot: str = "", prefix: str = "", pattern: str = "", limit: int = 50) -> str:
    import glob as _glob
    import os

    requested_limit = limit
    limit = _bounded_limit(limit)
    if not projectRoot:
        projectRoot = _detect_project_root() or "."
    if not os.path.isdir(projectRoot):
        return f"code_files: directory not found: {projectRoot}"
    if pattern:
        matches = sorted(_glob.glob(os.path.join(projectRoot, pattern), recursive=True))
        rels = [os.path.relpath(m, projectRoot).replace(os.sep, "/") for m in matches if os.path.isfile(m)]
        if not rels:
            return f"No files matching '{pattern}'."
        parts = [f"code_files pattern={pattern!r} total={len(rels)} shown={min(len(rels), limit)}"]
        parts.extend(rels[:limit])
        if len(rels) > limit:
            parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow pattern")
        if requested_limit > _MAX_CODE_LINES:
            parts.append(f"capped: requested {requested_limit}")
        return "\n".join(parts)

    indexer = _ensure_code_index(projectRoot)
    try:
        files = indexer.list_files(prefix=prefix, limit=limit)
        parts = [f"code_files prefix={prefix!r} shown={len(files)} limit={limit}"]
        parts.extend(f"file: {f['file_path']} symbols={f['symbol_count']}" for f in files)
        if len(files) == limit:
            parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow prefix")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(description="Explore symbols with compact source and call paths. Auto-indexes, bounds source to 50 lines, and falls back to text search.")
def code_explore(query: str, projectRoot: str = "", limit: int = 10) -> str:
    import os
    import subprocess as _subprocess

    limit = _bounded_limit(limit)
    from indexer import CODE_DB_FILENAME, CodeIndexer
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        try:
            _ci = CodeIndexer(projectRoot)
        except ValueError as e:
            return str(e)
        try:
            _ci.index_project(_max_workers=4)
        finally:
            _ci.close()
    indexer = CodeIndexer(projectRoot)
    try:
        # Try exact symbol name or ID first (from code_find)
        symbols = []
        try:
            sid = int(query)
            sym = indexer.get_symbol(sid)
            if sym:
                symbols = [sym]
        except ValueError:
            exact = indexer.get_symbol_by_name(query)
            if len(exact) == 1:
                symbols = exact
            elif len(exact) > 1:
                # Multiple exact matches — prefer the ones with most context
                symbols = exact[:limit]

        if not symbols:
            symbols = indexer.search_symbols(query, limit=limit)

        # Natural language fallback: use ripgrep to find matching lines in source files
        if not symbols:
            try:
                result = _rg_text_search(projectRoot, _grouped_text_query(query), "", True, 0)
                if result.returncode in (0, 1) and result.stdout.strip():
                    lines = result.stdout.strip().splitlines()
                    shown = lines[:limit]
                    root_prefix = os.path.abspath(projectRoot).rstrip(os.sep) + os.sep
                    parts = [f"code_explore text={len(lines)} shown={len(shown)} query={query!r}"]
                    parts.extend(line.replace(root_prefix, "") for line in shown)
                    if len(lines) > limit:
                        parts.append(f"more: increase limit (max {_MAX_CODE_LINES}) or narrow query")
                    return "\n".join(parts)
            except FileNotFoundError:
                pass
            except _subprocess.TimeoutExpired:
                pass

        if not symbols:
            return f"code_explore: no matches for {query!r}"
        parts = []
        for sym in symbols[:limit]:
            loc = _fmt_loc(sym['file_path'])
            start_line = sym.get('start_line') or 1
            end_line = sym.get('end_line') or start_line
            parts.append(f"symbol {sym['id']} {sym['symbol_name']} {loc}:{start_line}-{end_line} type={sym['symbol_type']}")
            if sym.get('signature'):
                parts.append(f"signature: {sym['signature']}")
            callers = indexer.get_callers(sym['symbol_name'])
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:5])
                parts.append(f"callers: {cstr}")
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:5])
                parts.append(f"calls: {cstr}")
            abs_fp = os.path.join(projectRoot, sym['file_path'])
            if os.path.isfile(abs_fp):
                with open(abs_fp) as f:
                    lines = f.read().splitlines()
                start = max(0, start_line - 1)
                end = min(len(lines), end_line, start + _MAX_CODE_LINES)
                parts.append(f"source: {sym['file_path']}:{start + 1}-{end}")
                parts.extend(lines[i] for i in range(start, end))
                if end < end_line:
                    parts.append(f"more: code_read(filePath={sym['file_path']!r}, offset={end + 1}, limit={_MAX_CODE_LINES})")
        return "\n".join(parts) if parts else "code_explore: no results"
    finally:
        indexer.close()


@server.tool(description="One-shot symbol context: definition, bounded source, callers, callees, imports, related tests, and next action.")
def code_context(query: str, projectRoot: str = "", limit: int = 10) -> str:
    import os

    if not projectRoot:
        projectRoot = _detect_project_root()
    if not os.path.isdir(projectRoot):
        return f"code_context: directory not found: {projectRoot}"
    limit = _bounded_limit(limit)
    indexer = _ensure_code_index(projectRoot)
    try:
        symbols = []
        try:
            symbol_id = int(query)
            symbol = indexer.get_symbol(symbol_id)
            if symbol:
                symbols = [symbol]
        except ValueError:
            symbols = indexer.get_symbol_by_name(query)
        if not symbols:
            symbols = indexer.search_symbols(query, limit=limit)
        if not symbols:
            return f"code_context: no symbol match: {query!r}"

        symbol = symbols[0]
        file_path = symbol["file_path"]
        start_line = max(1, symbol.get("start_line") or 1)
        source = code_read(filePath=file_path, projectRoot=projectRoot, offset=start_line, limit=_MAX_CODE_LINES)
        callers = indexer.get_callers(symbol["symbol_name"])
        callees = indexer.get_callees(symbol["symbol_name"], file_path)
        imports = [
            dict(row)
            for row in indexer.conn.execute(
                "SELECT DISTINCT from_name, line_number FROM code_edges "
                "WHERE project_id = ? AND file_path = ? AND edge_type = 'imports' "
                "ORDER BY line_number LIMIT ?",
                (indexer.project_id, file_path, limit),
            )
        ]
        stem = os.path.splitext(os.path.basename(file_path))[0].lower()
        tests = [
            f["file_path"]
            for f in indexer.list_files(limit=0)
            if "test" in f["file_path"].lower() and stem in f["file_path"].lower()
        ][:limit]

        parts = [f"code_context symbol={symbol['symbol_name']!r} file={file_path}:{start_line} language={symbol.get('language', '?')}"]
        if symbol.get("signature"):
            parts.append(f"signature: {symbol['signature']}")
        parts.append(source)
        parts.append("callers: " + (", ".join(f"{c['symbol_name']}@{c['file_path']}:{c['line_number']}" for c in callers[:limit]) or "none"))
        parts.append("callees: " + (", ".join(f"{c['to_name']}@{c['file_path']}:{c['line_number']}" for c in callees[:limit]) or "none"))
        parts.append("imports: " + (", ".join(str(item.get("from_name", "")) for item in imports) or "none"))
        parts.append("tests: " + (", ".join(tests) or "none found"))
        parts.append(f"next: code_explore({symbol['symbol_name']!r}, projectRoot={projectRoot!r}, limit={limit})")
        return "\n".join(parts)
    finally:
        indexer.close()


@_optional_tool(description="Analyze impact of changing a symbol (transitive reverse deps).")
def code_impact(symbolName: str, projectRoot: str = "", depth: int = 2, limit: int = 30) -> str:
    import os

    from indexer import CODE_DB_FILENAME, CodeIndexer
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    limit = _bounded_limit(limit)
    if not os.path.exists(db_path):
        indexer = _ensure_code_index(projectRoot)
    else:
        indexer = CodeIndexer(projectRoot)
    try:
        results = indexer.get_impact(symbolName, depth=depth, limit=limit)
        if not results:
            return f"code_impact: no impact for {symbolName!r}"
        parts = [f"code_impact symbol={symbolName!r} shown={len(results)} depth={depth} limit={limit}"]
        for r in results:
            loc = _fmt_loc(r['file_path'])
            via = f" via={r['via']}" if r.get('via') else ""
            parts.append(f"impact id={r['id']} {r['symbol_name']} {loc}:{r['line_number']}{via}")
        if len(results) >= limit:
            parts.append(f"more: increase limit (max {_MAX_CODE_LINES})")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(description="Compact review context for changed files: blast radius, entry points, test gaps, key risks. Supports query filtering to narrow results to specific terms.")
def get_review_context(
    files: list[str],
    query: str = "",
    projectRoot: str = "",
    maxTokens: int = 300,
) -> str:
    import os
    import re as _re

    from indexer import CODE_DB_FILENAME, CodeIndexer

    if not projectRoot:
        projectRoot = _detect_project_root()
    if not os.path.isdir(projectRoot):
        return f"Directory not found: {projectRoot}"
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return "Code graph not initialized. Run code_init(projectRoot) first."

    indexer = CodeIndexer(projectRoot)
    try:
        norm_files = []
        for f in files:
            nf = f.replace("\\", "/")
            if os.path.isabs(nf):
                try:
                    nf = os.path.relpath(nf, projectRoot).replace("\\", "/")
                except ValueError:
                    pass
            elif nf.startswith("./"):
                nf = nf[2:]
            norm_files.append(nf)

        # 1. CHANGED
        changed_line = f"CHANGED: {', '.join(norm_files)}"

        # Find symbols in changed files
        changed_symbols = []
        for nf in norm_files:
            changed_symbols.extend(indexer.list_symbols_by_file(nf, limit=0))

        # Filter by query if provided
        if query and query.strip():
            q_terms = _re.findall(r'[A-Za-z_][A-Za-z0-9_]*', query)
            if q_terms:
                q_lower = [t.lower() for t in q_terms]
                filtered = []
                for sym in changed_symbols:
                    name_lower = sym.get("symbol_name", "").lower()
                    sig_lower = (sym.get("signature") or "").lower()
                    if any(qt in name_lower for qt in q_lower) or any(qt in sig_lower for qt in q_lower):
                        filtered.append(sym)
                changed_symbols = filtered

        # 2. BLAST RADIUS
        blast_files_dict = {}
        for sym in changed_symbols:
            impacts = indexer.get_impact(sym["symbol_name"], depth=2, limit=10)
            for imp in impacts:
                fp = imp.get("file_path")
                if fp and fp not in norm_files and fp not in blast_files_dict:
                    blast_files_dict[fp] = imp.get("via")

        blast_files = list(blast_files_dict.keys())[:10]
        blast_line = f"BLAST RADIUS ({len(blast_files)} files): {', '.join(blast_files)}" if blast_files else ""

        # 3. ENTRY POINTS
        entry_points = []
        for sym in changed_symbols:
            name = sym["symbol_name"]
            callers = indexer.get_callers(name)
            callees = indexer.get_callees(name, sym["file_path"])
            inbound_from_outside = [c for c in callers if c["file_path"] not in norm_files]
            outbound_to_changed = [
                c for c in callees
                if c.get("file_path") in norm_files
                or (c.get("to_name") and any(s["symbol_name"] == c["to_name"] for s in changed_symbols))
            ]
            if inbound_from_outside and not outbound_to_changed:
                entry_points.append(sym)

        if not entry_points:
            for sym in changed_symbols:
                name = sym["symbol_name"]
                callers = indexer.get_callers(name)
                if any(c["file_path"] not in norm_files for c in callers):
                    entry_points.append(sym)

        seen_ep = set()
        dedup_ep = []
        for ep in entry_points:
            if ep["symbol_name"] not in seen_ep:
                seen_ep.add(ep["symbol_name"])
                dedup_ep.append(ep)

        ep_strs = []
        for ep in dedup_ep:
            sname = ep["symbol_name"]
            stype = ep.get("symbol_type", "")
            if stype in ("function", "method") or "(" not in sname:
                ep_strs.append(f"{sname}()")
            else:
                ep_strs.append(sname)

        entry_line = f"ENTRY POINTS: {', '.join(ep_strs)}" if ep_strs else ""

        # 4. KEY RISK
        key_risk_items = []
        for br_file in blast_files:
            c = indexer.conn.cursor()
            rows = c.execute(
                """SELECT DISTINCT cs.file_path
                   FROM code_edges ce
                   JOIN code_symbols cs ON cs.symbol_name = ce.to_name
                   WHERE ce.file_path = ? AND ce.project_id = ?""",
                (br_file, indexer.project_id),
            ).fetchall()
            target_changed_files = {r["file_path"] for r in rows if r["file_path"] in norm_files}
            if len(target_changed_files) > 1:
                key_risk_items.append(
                    f"{br_file} imports from both changed files"
                    if len(norm_files) == 2
                    else f"{br_file} imports from multiple changed files"
                )

        key_risk_line = f"KEY RISK: {'; '.join(key_risk_items)}" if key_risk_items else ""

        # 5. CALLERS
        caller_items = []
        for ep in dedup_ep:
            name = ep["symbol_name"]
            callers = indexer.get_callers(name)
            outside_callers = [c for c in callers if c["file_path"] not in norm_files]
            if outside_callers:
                locs = [f"{c['file_path']}:L{c['line_number']}" for c in outside_callers[:5]]
                caller_items.append(f"{name}() ← {', '.join(locs)}")

        caller_line = f"CALLERS: {'; '.join(caller_items)}" if caller_items else ""

        # 6. TEST GAPS
        all_indexed_files = {f["file_path"] for f in indexer.list_files(limit=0)}
        test_gap_items = []
        for br_file in blast_files:
            base = os.path.basename(br_file)
            name_no_ext, ext = os.path.splitext(base)
            dir_name = os.path.dirname(br_file)

            candidates = [
                os.path.join(dir_name, f"test_{base}"),
                os.path.join(dir_name, f"{name_no_ext}_test{ext}"),
                os.path.join("tests", f"test_{base}"),
                os.path.join("tests", f"{name_no_ext}_test{ext}"),
                os.path.join("test", f"test_{base}"),
                os.path.join(dir_name, f"{name_no_ext}.test{ext}"),
                os.path.join(dir_name, f"{name_no_ext}.spec{ext}"),
            ]
            has_test = False
            for cand in candidates:
                cand_norm = cand.replace("\\", "/")
                if cand_norm in all_indexed_files or os.path.exists(os.path.join(projectRoot, cand_norm)):
                    has_test = True
                    break
            if not has_test:
                test_gap_items.append(f"{br_file} has no test coverage")

        test_gap_line = f"TEST GAPS: {'; '.join(test_gap_items)}" if test_gap_items else ""

        # Add query info if provided
        query_line = f"FILTERED BY: {query}" if query else ""

        # Budget truncation order: Drop TEST GAPS first, then CALLERS, then KEY RISK
        sections = [
            changed_line,
            blast_line,
            entry_line,
            key_risk_line,
            caller_line,
            test_gap_line,
            query_line,
        ]

        active = [s for s in sections if s]
        max_chars = maxTokens * 4
        result = "\n".join(active)

        if len(result) > max_chars and test_gap_line in active:
            active.remove(test_gap_line)
            result = "\n".join(active)

        if len(result) > max_chars and caller_line in active:
            active.remove(caller_line)
            result = "\n".join(active)

        if len(result) > max_chars and key_risk_line in active:
            active.remove(key_risk_line)
            result = "\n".join(active)

        return result
    finally:
        indexer.close()


# ── End Code Graph Tools ──────────────────────────────────────────




@server.tool(description="Mid-session memory refresh or topic switch ONLY (context is auto-injected at session start — do NOT call then). Loads state, decisions, facts, code stats for a topic.")
def getContext(topic: str = "", project: str = "", query: str = "") -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    if project and not topic:
        topic = project
    if not topic:
        return "ctx: (unknown)\n  state: Provide `project='folder'` or `topic='name'`."

    lines = [f"ctx: {topic}"]

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        lines.append("  state: (no memory db yet — will be created on first write)")
        return "\n".join(lines)

    storage = StorageManager(db_path)
    manager = SessionManager(storage)

    try:
        storage.connection.execute(
            "INSERT OR IGNORE INTO notes (topic, kind, content, agent_id, turn_index) VALUES (?, 'turn', ?, 'system', 0)",
            (SessionManager.normalize_topic(topic), f"Context retrieved (query: {query or 'none'})"),
        )
        storage.connection.commit()
    except Exception:
        pass

    ctx = manager.get_context(topic, query=query)
    lines.extend(ctx.splitlines()[1:])  # skip the "ctx:" line already added

    try:
        from indexer import CODE_DB_FILENAME
        pr = _detect_project_root()
        cdb = os.path.join(pr, CODE_DB_FILENAME)
        if os.path.isfile(cdb):
            import sqlite3 as _sc
            _c = _sc.connect(cdb)
            try:
                count = _c.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0]
                files = _c.execute("SELECT COUNT(DISTINCT file_path) FROM code_symbols").fetchone()[0]
                lines.append(f"  code: {files} files, {count} symbols")
            except Exception:
                pass
            finally:
                _c.close()
        else:
            lines.append("  code: (no index yet — auto-indexes on first code_find)")
    except Exception:
        pass

    return "\n".join(lines)


@server.tool(description="Read planet details: state, notes, files. raw=true returns notes for summarization.")
def read_planet(topic: str, raw: bool = False, limit: int = 50) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if raw:
        return manager.summarize_planet(topic, limit=limit)

    from storage.planets import _get_notes
    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    proxy = manager.get_planet(topic)
    if not proxy:
        return f"No planet found for topic '{topic}'."

    m = proxy.metadata
    notes = _get_notes(storage.connection, manager.normalize_topic(topic))

    display = m.get("display_topic") or m.get("topic") or topic
    next_steps = m.get("next_steps", [])
    files = m.get("files", [])
    commands = m.get("commands", [])

    lines = [f"{display} | {m.get('status') or 'active'}"]
    lines.append(f"  goal: {m.get('goal') or '—'}")
    lines.append(f"  state: {m.get('current_state') or '—'}")
    lines.append(f"  next: {m.get('next_step') or '—'}")
    if next_steps:
        lines.append(f"  steps: {', '.join(next_steps)}")
    if files:
        lines.append(f"  files: {', '.join(files)}")
    if commands:
        lines.append(f"  cmds: {', '.join(commands)}")
    if m.get("handoff"):
        lines.append(f"  handoff: {m['handoff']}")
    if notes:
        lines.append(f"  notes ({len(notes)}):")
        for n in notes[:10]:
            lines.append(f"    [{n['kind'][:4]}] {n['content'][:200]}")
    return "\n".join(lines)


@server.tool(description="Call IMMEDIATELY when you make a decision, apply a fix, or learn a fact — do not defer to session end. Also use for session summaries (summary + activity=\"done\"). topic required.")
def logInteraction(
    topic: str = "",
    decision: str = "",
    fact: str = "",
    summary: str = "",
    currentState: str = "",
    nextStep: str = "",
    activity: str = "",
    planet: str = "",
) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    if not topic and planet:
        topic = planet
    if not topic:
        return "Error: 'topic' (or 'planet') argument is required — the planet/topic name to log into."

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    parts = []

    for kind, val in [("decision", decision), ("fact", fact), ("summary", summary)]:
        if val:
            manager.add_note(topic, topic, kind, val)
            parts.append(f"note({kind})")

    if currentState or nextStep:
        manager.update_planet(
            topic, topic,
            current_state=currentState or None,
            next_step=nextStep or None,
        )
        parts.append("planet_updated")

    if activity:
        manager.log_chat_to_planet(topic, topic, activity, agent_id="system", _sender="system")
        parts.append("turn_logged")

    if not parts:
        return "no-op: logInteraction called with no content. Pass at least one of: decision='what was decided and why', fact='what is now known', summary='what happened this session', currentState='current progress', nextStep='next action'. Example: logInteraction(topic='myproject', decision='Chose SQLite because it requires no separate server process.')"

    return f"{' + '.join(parts)} for '{topic}'."


@server.tool(description="Create or update a planet with goal, state, next step, files.")
def update_planet(
    topic: str,
    currentState: str = "",
    nextStep: str = "",
    status: str = "",
    goal: str = "",
    filePath: str = "",
    command: str = "",
    handoff: str = "",
) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    manager.update_planet(
        topic, topic,
        current_state=currentState or None,
        next_step=nextStep or None,
        status=status or None,
        goal=goal or None,
        file_path=filePath or None,
        command=command or None,
        handoff=handoff or None,
    )
    return f"Planet '{topic}' updated."





@server.tool(description="Trim old notes, keep summaries + 30 recent.")
def compact_planet(topic: str) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    count_before = manager.get_note_count(topic)
    manager.compact_planet("default", topic)
    count_after = manager.get_note_count(topic)
    return f"Compacted '{topic}': {count_before} notes -> {count_after} notes kept."


@server.tool(description="List all planets/topics.")
def list_planets() -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    planets = manager.list_planets()
    if not planets:
        return "No planets found. Create one with update_planet."
    lines = ["# Available Planets"]
    for p in planets:
        name = p["display_topic"] or p["topic"]
        status_tag = f" [{p['status']}]" if p["status"] and p["status"] != "active" else ""
        lines.append(f"- {name}{status_tag}")
    return "\n".join(lines)


@server.tool(description="Query-aware recall: FTS5 search memory notes + code symbols for a user prompt. Same engine as `mem prompt-context` (used by UserPromptSubmit hooks). Prints nothing when no relevant context.")
def prompt_context(query: str, topic: str = "", projectRoot: str = "", limit: int = 3) -> str:
    """Recall relevant memory + code for a user prompt via FTS5.

    Searches notes_fts (topic-scoped when topic given) and the per-project
    .basemem.code.db code_symbols_fts index. Returns a compact block or ''.
    """
    import os as _os
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    try:
        from storage.notes import tokenize_query as _tok
    except Exception:
        _tok = None

    text = (query or "").strip()
    if len(text) < 8:
        return ""
    if len(text) > 2000:
        text = text[:2000]
    tokens = _tok(text) if _tok else []
    if not tokens:
        return ""

    db_path = get_db_path()
    if not _os.path.isfile(db_path):
        return ""
    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    mem_hits: list = []
    try:
        if hasattr(manager, "search_notes_fts"):
            mem_hits = manager.search_notes_fts(topic or "general", " ".join(tokens[:12]), limit=limit) or []
    except Exception:
        mem_hits = []

    code_hits: list = []
    try:
        from indexer import CODE_DB_FILENAME, CodeIndexer
        croot = _os.path.abspath(projectRoot or _os.getcwd())
        cur = croot
        found = None
        for _ in range(4):
            cand = _os.path.join(cur, CODE_DB_FILENAME)
            if _os.path.isfile(cand):
                found = cur
                break
            parent = _os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        if found:
            indexer = CodeIndexer(found)
            try:
                code_hits = indexer.search_symbols(" ".join(tokens[:8]), limit=limit) or []
            finally:
                try:
                    indexer.close()
                except Exception:
                    pass
    except Exception:
        code_hits = []
    if not mem_hits and not code_hits:
        return ""
    lines: list[str] = []
    if mem_hits:
        lines.append("[Relevant memory]")
        for n in mem_hits[:limit]:
            kind = n.get("kind") or "note"
            title = (n.get("title") or "")[:100]
            content = " ".join((n.get("content") or "").split())[:300]
            lines.append(f"- ({kind}) {title}: {content}" if title else f"- ({kind}) {content}")
    if code_hits:
        lines.append("[Relevant code]")
        for s in code_hits[:limit]:
            sig = " ".join((s.get("signature") or "").split())[:160]
            loc = f"{s.get('file_path')}:{s.get('start_line')}-{s.get('end_line')}"
            desc = f"{s.get('symbol_name')} ({s.get('symbol_type')}) {loc}"
            if sig:
                desc += f" — {sig}"
            lines.append(f"- {desc}"[:350])
    out = "\n".join(lines)
    return out[:1497] + "..." if len(out) > 1500 else out


@server.tool(description="Full-text search across planets, notes, nodes.")
def search_nodes(query: str, limit: int = 10) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    results = manager.search_all(query, limit=limit)
    lines = [f"# Search results for: '{query}'\n"]
    count = 0

    for r in results.get("planets", []):
        if count >= limit:
            break
        name = r.get("display_topic") or r["topic"]
        preview = (r.get("current_state") or "")[:200]
        lines.append(f"🪐 **Planet: {name}**")
        if preview:
            lines.append(f"   {preview}")
        lines.append("")
        count += 1

    for r in results.get("notes", []):
        if count >= limit:
            break
        preview = (r.get("content") or "")[:200]
        lines.append(f"[note] **{r['topic']} [{r['kind']}]**")
        lines.append(f"   {preview}")
        lines.append("")
        count += 1

    # Old nodes from StorageManager FTS
    old_ids = storage.search_nodes_fts(query, limit=limit - count)
    for nid in old_ids:
        if count >= limit:
            break
        n = storage.get_node(nid)
        if n:
            preview = (n.content or "")[:200]
            lines.append(f"○ **{n.title}** ({n.node_type.value})")
            lines.append(f"   {preview}")
            lines.append("")
            count += 1

    if count == 0:
        return "No matches found."

    return "\n".join(lines)


@server.tool(description="Search notes by topic, kind, text.")
def search_notes(topic: str = "", kind: str = "", query: str = "", limit: int = 10) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    rows = manager.search_notes(topic, kind=kind, query=query, limit=limit)

    if not rows:
        return "No matching notes found."

    lines = [f"# Notes for '{topic}'" + (f" (kind: {kind})" if kind else "")]
    for r in rows:
        preview = (r.get("content") or "")[:200]
        lines.append(
            f"\n**[{r['kind'].upper()}] (id={r['id']})**\n{preview}"
        )
    return "\n".join(lines)


@_optional_tool(description="Read a full node by ID.")
def get_node(nodeId: str | int) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    nid = SessionManager._parse_note_id(nodeId)
    if nid is None:
        return f"Invalid node ID: {nodeId}"

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    row = manager.get_note(nid)
    if not row:
        return f"No node found with id '{nodeId}'."

    updated = row.get("updated_at") or "N/A"
    return (
        f"**ID:** {row['id']}\n"
        f"**Topic:** {row['topic']}\n"
        f"**Kind:** {row['kind']}\n"
        f"**Title:** {row.get('title', '')}\n"
        f"**Created:** {row['created_at']}\n"
        f"**Updated:** {updated}\n"
        f"\n**Content:**\n{row['content']}"
    )


@server.tool(description="Link two notes or planets. kind='notes' (default) or 'planets'.")
def link(fromId: str | int, toId: str | int, linkType: str = "related", weight: float = 1.0, kind: str = "notes") -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if kind == "planets":
        ok, msg = manager.link_planets(str(fromId), str(toId), linkType, weight)
    else:
        ok, msg = manager.link_notes(fromId, toId, linkType, weight)
    return msg


@server.tool(description="Update a note's pinned status and/or tags.")
def note_update(noteId: str | int, pinned: bool | None = None, tags: str | None = None) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    return manager.note_update(noteId, pinned=pinned, tags=tags)


# ── Task MCP tools ─────────────────────────────────────────────


@server.tool(description="Create a task on a planet. Returns the task id.")
def task_create(topic: str, title: str, priority: str = "medium", depends_on: list | None = None, files: list | None = None, notes: list | None = None) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if notes:
        notes = [int(n.replace("note-", "")) if isinstance(n, str) and "note-" in n else int(n) for n in notes]
    if depends_on:
        depends_on = [int(d.replace("task-", "")) if isinstance(d, str) and "task-" in d else int(d) for d in depends_on]
    result = manager.create_task(topic, title, priority=priority, depends_on=depends_on, files=files, notes=notes)
    deps = json.loads(result.get("depends_on", "[]"))
    parts = [f"Task created: task-{result['id']} [{result['status']}/{result['priority']}] {result['title']}"]
    if deps:
        parts.append(f"  depends_on: {deps}")
    return "\n".join(parts)


@server.tool(description="Update a task's status, priority, files, or notes.")
def task_update(task_id: int, status: str | None = None, priority: str | None = None, files: list | None = None, notes: list | None = None) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if notes:
        notes = [int(n.replace("note-", "")) if isinstance(n, str) and "note-" in n else int(n) for n in notes]
    ok, msg = manager.update_task(task_id, status=status, priority=priority, files=files, notes=notes)
    return msg


@server.tool(description="Batch-update multiple tasks in one call using {task_id, status, priority, files, notes} objects. Returns one compact result per task.")
def task_update_many(updates: list[dict]) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    results = []
    for update in updates:
        task_id = update.get("task_id")
        if task_id is None:
            results.append("error: missing task_id")
            continue
        notes = update.get("notes")
        if notes:
            notes = [int(n.replace("note-", "")) if isinstance(n, str) and "note-" in n else int(n) for n in notes]
        ok, message = manager.update_task(
            int(task_id),
            status=update.get("status"),
            priority=update.get("priority"),
            files=update.get("files"),
            notes=notes,
        )
        results.append(f"task-{task_id}: {'ok' if ok else 'error'} {message}")
    return f"task_update_many updated={len(results)} errors={sum(1 for r in results if r.startswith('error'))}\n" + "\n".join(results)


@server.tool(description="List tasks, optionally filtered by topic, status, priority.")
def task_list(topic: str | None = None, status: str | None = None, priority: str | None = None) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    tasks = manager.list_tasks(topic=topic, status=status, priority=priority)
    if not tasks:
        return "No tasks found."
    lines = [f"Tasks ({len(tasks)}):\n"]
    for t in tasks:
        deps = json.loads(t.get("depends_on", "[]"))
        dep_str = f" depends_on: {deps}" if deps else ""
        lines.append(f"  task-{t['id']} [{t['status']}/{t['priority']}] {t['title']}{dep_str}")
    return "\n".join(lines)


@server.tool(description="Block a task. Optionally provide a reason (stored as an issue note).")
def task_block(task_id: int, reason: str | None = None) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if reason:
        row = manager.storage.connection.cursor().execute(
            "SELECT topic, title, notes FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row:
            note = manager.add_note("", row["topic"], "issue", reason, title=f"Blocked: {row['title']}", status="open")
            nid = int(note["id"].replace("note-", ""))
            notes_str = row["notes"] if row["notes"] else "[]"
            existing = json.loads(notes_str)
            if nid not in existing:
                existing.append(nid)
                # Normalize to ints: filter out non-numeric entries, convert strings that look like ints
                ints = [int(x) for x in existing if isinstance(x, (int, str)) and str(x).lstrip('-').isdigit()]
                manager.update_task(task_id, notes=ints)
    ok, msg = manager.update_task(task_id, status="blocked")
    return "Blocked. " + msg if ok else msg


# ── Planet links ─────────────────────────────────────────────


@server.tool(description="Get planets linked to a planet.")
def get_planet_links(planet: str) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    links = manager.get_planet_links(planet)
    if not links:
        return f"No planet links found for '{planet}'."
    lines = [f"Planets linked to '{planet}':\n"]
    for link in links:
        lines.append(f"- {link['planet']} [{link['relation']}] (w={link['weight']})")
    return "\n".join(lines)


# ── Memory tiers ──────────────────────────────────────────────


@_optional_tool(description="Set memory tier: hot, warm, compacted.")
def set_memory_state(topic: str, state: str) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.set_memory_state(topic, state)
    return msg


# ── Collapsed graph tool ──────────────────────────────────────


@server.tool(description="Get graph neighbors (depth=1), ranked list, or subgraph JSON (depth>1), optionally including virtual AST code nodes.")
def get_graph(noteId: str | int, depth: int = 1, minWeight: float = 0.0, ranked: bool = False, includeCode: bool = False) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    from graph.engine import GraphEngine
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(noteId)
    if nid is None and not str(noteId).startswith("code:"):
        return f"Invalid note ID: {noteId}"

    if depth > 1:
        import json
        result = manager.get_subgraph(nid, depth=depth, min_weight=minWeight) if nid else {"nodes": [], "edges": []}
        if includeCode:
            ge = GraphEngine(storage)
            vgraph = ge.get_virtual_code_overlay(project_root=_detect_project_root())
            for vnode_id, vnode in vgraph["nodes"].items():
                result.setdefault("nodes", []).append(vnode)
            for vedge in vgraph["edges"]:
                result.setdefault("edges", []).append(vedge)
        return json.dumps(result, indent=2)

    if ranked:
        ranked_list = manager.rank_neighbors(nid) if nid else []
        if not ranked_list:
            return "No neighbors found."
        filtered = [r for r in ranked_list if r['weight'] >= minWeight]
        if not filtered:
            return "No neighbors found at this weight threshold."
        lines = [f"Neighbors ranked by weight:\n"]
        for i, r in enumerate(filtered, 1):
            lines.append(f"  {i}. note-{r['id']} (w={r['weight']}, c={r.get('confidence','?')}) {r['title'] or r['content'][:60]}")
        return "\n".join(lines)

    neighbors = manager.get_neighbors_weighted(nid, depth=1, min_weight=minWeight) if nid else []
    lines = [f"Neighbors (min_weight={minWeight}):\n"]
    for r in neighbors:
        lines.append(f"  note-{r['id']} [{r['link_type']}] (w={r['weight']}) {r['title'] or r['content'][:60]}")

    if includeCode:
        ge = GraphEngine(storage)
        note_row = storage.connection.execute("SELECT title, content FROM notes WHERE id=?", (nid,)).fetchone() if nid else None
        q = note_row["title"] if note_row else ""
        vgraph = ge.get_virtual_code_overlay(project_root=_detect_project_root(), symbol_name=q)
        if vgraph["nodes"]:
            lines.append("\nVirtual AST Code Nodes & Edges:")
            for vnode_id, vnode in list(vgraph["nodes"].items())[:20]:
                lines.append(f"  {vnode_id} [{vnode.get('symbol_type', 'symbol')}] {vnode.get('title') or ''}")
            for vedge in list(vgraph["edges"])[:20]:
                lines.append(f"    edge: {vedge['from_id']} --[{vedge['edge_type']}]--> {vedge['to_id']}")

    if len(lines) == 1:
        return "No neighbors found."
    return "\n".join(lines)


@_optional_tool(description="Two notes for agent similarity comparison.")
def compute_similarity(noteIdA: str, noteIdB: str) -> str:
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid_a = manager._parse_note_id(noteIdA)
    nid_b = manager._parse_note_id(noteIdB)
    if nid_a is None or nid_b is None:
        return "One or both note IDs are invalid."
    rows = manager.storage.connection.cursor().execute(
        "SELECT id, topic, kind, content, title FROM notes WHERE id IN (?, ?)",
        (nid_a, nid_b),
    ).fetchall()
    if len(rows) != 2:
        return "One or both notes not found."
    result = []
    for r in rows:
        result.append(f"--- note-{r['id']} ({r['topic']}/{r['kind']}) ---")
        if r["title"]:
            result.append(f"Title: {r['title']}")
        result.append(r["content"])
    result.append("")
    result.append("Agent: decide a similarity score (0-1) and call link_notes with weight=<score>.")
    return "\n".join(result)


@server.tool(description="Automatically extract decisions & facts from text into structured memory notes.")
def extract_memories(topic: str, text: str) -> str:
    import json
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    extracted = manager.auto_extract_memories(topic, text)
    if not extracted:
        return f"No decisions or key facts detected to extract for topic '{topic}'."
    return json.dumps({"topic": topic, "extracted_count": len(extracted), "items": extracted}, indent=2)


@server.tool(description="Scan memory notes for a topic to detect and resolve contradictions automatically.")
def resolve_contradictions(topic: str) -> str:
    import json
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.resolve_contradictions(topic)
    return json.dumps(result, indent=2)


@server.tool(description="Multi-layer context re-ranking combining FTS similarity, graph distance, and recency.")
def rank_context(topic: str, query: str = "", limit: int = 20) -> str:
    import json
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ranked = manager.rank_context(topic, query=query, limit=limit)
    if not ranked:
        return f"No context notes found for topic '{topic}'."
    return json.dumps({"topic": topic, "count": len(ranked), "results": ranked}, indent=2)


@_optional_tool(description="Notes + query for agent reranking.")
def rerank(query: str, noteIds: list) -> str:
    """Return query + note contents for agent-driven reranking."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ids = []
    for nid in noteIds:
        parsed = manager._parse_note_id(str(nid))
        if parsed is not None:
            ids.append(parsed)
    if not ids:
        return "No valid note IDs provided."
    placeholders = ",".join("?" for _ in ids)
    rows = manager.storage.connection.cursor().execute(
        f"SELECT id, topic, kind, content, title FROM notes WHERE id IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()
    parts = [f"Query: {query}", f"Candidate notes ({len(rows)}):\n"]
    for r in rows:
        parts.append(f"--- note-{r['id']} ({r['topic']}/{r['kind']}) ---")
        if r["title"]:
            parts.append(f"Title: {r['title']}")
        parts.append(r["content"][:500])
        parts.append("")
    parts.append("Agent: reorder the note IDs by relevance to the query and return them.")
    return "\n".join(parts)


@server.tool(description="Maintain auto-links: decay weights by a factor and/or prune below a threshold. Decay runs before prune so pruning reflects decayed weights. At least one of decayFactor or pruneThreshold must be provided.")
def edge_maintain(planet: str | None = None, decayFactor: float | None = None, pruneThreshold: float | None = None) -> str:
    """Apply decay and/or prune to auto-links. Decay runs first, then prune reflects decayed weights."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    return manager.edge_maintain(planet=planet, decay_factor=decayFactor, prune_threshold=pruneThreshold)


# ── Session MCP Tools ──────────────────────────────────


@server.tool(description="Start a new session: track activity within a planet. Returns the session id.")
def session_start(topic: str, title: str, agent_id: str, session_id: int | None = None) -> str:
    """Create a new active session on the given planet, or resume an existing one if session_id is provided."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if session_id is not None:
        ok = manager.resume_session(session_id, agent_id)
        if not ok:
            return f"Session {session_id} not found."
        return f"Session {session_id} resumed. Agent: {agent_id}."
    sid = manager.create_session(topic, title, agent_id)
    return f"Session created: id={sid}, topic='{topic}', title='{title}', agent='{agent_id}'."


@server.tool(description="End or pause a session. pause=true sets status=paused without closing. Default: close with optional summary.")
def session_end(session_id: int, pause: bool = False, summary: str = "") -> str:
    """Close or pause a session."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    if pause:
        ok = manager.pause_session(session_id)
        if not ok:
            return f"Session {session_id} not found."
        return f"Session {session_id} paused."
    ok = manager.close_session(session_id, summary=summary or None)
    if not ok:
        return f"Session {session_id} not found."
    session = manager.get_session(session_id)
    status = session.get("status", "?")
    s = session.get("summary", "")
    return f"Session {session_id} closed. Status: {status}. Summary: {s[:200]}" if s else f"Session {session_id} closed."
@_optional_tool(description="Read a full session: metadata, stamped notes, and stamped tasks.")
def session_read(session_id: int) -> str:
    """Return session metadata with expanded notes and tasks."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    import json as _json
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    session = manager.get_session(session_id)
    if not session:
        return f"Session {session_id} not found."
    lines = [
        f"Session: {session.get('title', 'untitled')} (id={session_id})",
        f"  topic: {session.get('topic', '?')}",
        f"  status: {session.get('status', '?')}",
        f"  agent: {session.get('agent_id', '?')}",
        f"  started: {session.get('started_at', '?')}",
        f"  last active: {session.get('last_active_at', '?')}",
    ]
    if session.get("ended_at"):
        lines.append(f"  ended: {session['ended_at']}")
    if session.get("summary"):
        lines.append(f"  summary: {session['summary']}")
    note_ids = _json.loads(session.get("note_ids", "[]"))
    if note_ids:
        lines.append(f"  notes ({len(note_ids)}):")
        placeholders = ",".join("?" for _ in note_ids)
        cursor = manager.storage.connection.cursor()
        for r in cursor.execute(
            f"SELECT id, kind, title, content FROM notes WHERE id IN ({placeholders}) ORDER BY id ASC",
            note_ids,
        ):
            title = r["title"] or r["content"][:80]
            lines.append(f"    note-{r['id']} [{r['kind']}] {title[:200]}")
    task_ids = _json.loads(session.get("task_ids", "[]"))
    if task_ids:
        lines.append(f"  tasks ({len(task_ids)}):")
        placeholders = ",".join("?" for _ in task_ids)
        cursor = manager.storage.connection.cursor()
        for r in cursor.execute(
            f"SELECT id, status, priority, title FROM tasks WHERE id IN ({placeholders}) ORDER BY id ASC",
            task_ids,
        ):
            lines.append(f"    task-{r['id']} [{r['status']}/{r['priority']}] {r['title']}")
    return "\n".join(lines)


@server.tool(description="Recap the previous session for a topic: summary, recent decisions/facts, state, next step, and active/closed sessions.")
def session_recap(topic: str = "", limit: int = 3) -> str:
    import json
    from storage.db import StorageManager
    from storage.sessions import SessionManager

    if not topic:
        topic = os.path.basename(os.getcwd())
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    sessions = manager.list_sessions(topic)
    if not sessions:
        return f"session_recap: no sessions found for {topic!r}"
    sessions.sort(key=lambda item: item.get("last_active_at", ""), reverse=True)
    recent = sessions[: max(1, min(limit, 10))]
    last = next((s for s in recent if s.get("status") in ("closed", "paused")), recent[0])
    note_ids = json.loads(last.get("note_ids", "[]"))[-3:]
    notes = []
    if note_ids:
        placeholders = ",".join("?" for _ in note_ids)
        notes = [
            dict(row)
            for row in storage.connection.execute(
                f"SELECT id, kind, title, content FROM notes WHERE id IN ({placeholders}) ORDER BY id DESC",
                note_ids,
            ).fetchall()
        ]
    lines = [f"session_recap topic={topic!r} sessions={len(sessions)}"]
    lines.append(f"last: id={last.get('id')} title={last.get('title', 'untitled')!r} status={last.get('status', '?')} agent={last.get('agent_id', '?')} active={last.get('last_active_at', '?')}")
    if last.get("summary"):
        lines.append(f"summary: {last['summary']}")
    for note in notes:
        preview = (note.get("content") or "")[:160].replace("\n", " ")
        lines.append(f"note: {note.get('kind', '?')} {preview}")
    lines.append("next: resume_session or session_recap for the selected session")
    return "\n".join(lines)


@_optional_tool(description="List sessions for a topic, optionally filtered by status.")
def session_list(topic: str = "", status: str = "") -> str:
    """List sessions for a planet."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    sessions = manager.list_sessions(topic, status=status or None)
    if not sessions:
        return f"No sessions found for '{topic}'."
    lines = [f"Sessions for '{topic}' ({len(sessions)}):"]
    for s in sessions:
        title = s.get("title", "untitled")
        st = s.get("status", "?")
        agent = s.get("agent_id", "?")
        last = s.get("last_active_at", "?")[:19]
        lines.append(f"  id={s['id']} '{title}' [{st}] agent={agent} last={last}")
    return "\n".join(lines)


# ── Code Graph MCP Tools ─────────────────────────────────

@server.tool(description="STEP 2 after code_find: read a compact, bounded source window. filePath is relative to projectRoot; offset is 1-indexed; limit defaults to and is capped at 50. Source is unnumbered by default; set lineNumbers=true when explicit prefixes help.")
def code_read(filePath: str = "", projectRoot: str = "", offset: int = 0, limit: int = 50, path: str = "", lineNumbers: bool = False) -> str:
    """Read a bounded source window without requiring a code index."""
    import os

    if not filePath and path:
        filePath = path
    if not filePath:
        return "code_read: filePath is required"
    if not projectRoot:
        projectRoot = _detect_project_root() or "."
    if not os.path.isdir(projectRoot):
        return f"code_read: directory not found: {projectRoot}"
    if offset < 0:
        return "code_read: offset must be >= 0"

    requested_limit = limit
    limit = _bounded_limit(limit)
    abs_root = os.path.abspath(os.path.normpath(projectRoot))
    abs_fp = os.path.abspath(os.path.normpath(os.path.join(abs_root, filePath)))
    if not (abs_fp == abs_root or abs_fp.startswith(abs_root + os.sep)):
        return f"code_read: outside project root: {filePath}"
    if not os.path.isfile(abs_fp):
        return f"code_read: file not found: {filePath}"

    try:
        with open(abs_fp, errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return f"code_read: cannot read {filePath}: {e}"

    total = len(lines)
    start = max(0, offset - 1 if offset else 0)
    end = min(total, start + limit)
    if offset > total:
        return f"code_read: offset {offset} exceeds file length {total}"

    display_path = os.path.relpath(abs_fp, abs_root).replace(os.sep, "/")
    parts = [f"code_read {display_path}:{start + 1}-{end} total={total} shown={end - start}"]
    for i in range(start, end):
        parts.append(f"{i + 1}|{lines[i].rstrip()}" if lineNumbers else lines[i].rstrip())
    if end < total:
        parts.append(f"next: code_read(filePath={display_path!r}, offset={end + 1}, limit={_MAX_CODE_LINES})")
    if requested_limit > _MAX_CODE_LINES:
        parts.append(f"capped: requested {requested_limit}, returned {end - start}")
    return "\n".join(parts)


@server.tool(description="List available MCP resources (code schemas, project info, basemem config).")
def list_mcp_resources() -> str:
    parts = ["MCP Resources:"]

    # Code projects - lazy import to avoid tree_sitter dependency at call time
    try:
        from indexer import find_code_projects
        projects = find_code_projects()
        if projects:
            parts.append(f"\nCode Projects ({len(projects)}):")
            for p in sorted(projects, key=lambda x: x["name"]):
                parts.append(f"  resource://code/project/{p['name']} — {p['symbols']}s {p['files']}f at {p['root']}")
        else:
            parts.append("\nCode Projects: none found")
    except Exception:
        parts.append("\nCode Projects: (indexer unavailable)")

    # Code index schema
    parts.append("\nCode Index Schema:")
    parts.append("  resource://code/schema — table schema for code_symbols/code_edges/code_projects")

    # Active topic info
    parts.append("\nMemory:")
    parts.append("  resource://memory/stats — current session memory statistics")

    return "\n".join(parts)


@server.tool(description="Read an MCP resource by URI. Supported URIs: resource://code/schema, resource://code/project/<name>, and resource://memory/stats.")
def read_mcp_resource(uri: str) -> str:
    import os

    uri = uri.removeprefix("resource://")
    if uri == "memory/stats":
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        counts = {}
        for table in ("planets", "notes", "tasks", "sessions"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            except Exception:
                counts[table] = 0
        conn.close()
        return json.dumps({"resource": "memory/stats", "counts": counts}, indent=2)

    if uri == "code/schema":
        return """Code Index Schema (.basemem.code.db):

Tables:

  code_symbols:
    id (INTEGER PK), project_id (TEXT), file_path (TEXT),
    symbol_name (TEXT), symbol_type (TEXT), language (TEXT),
    kind (TEXT), start_line (INTEGER), end_line (INTEGER),
    start_col (INTEGER), end_col (INTEGER), signature (TEXT),
    docstring (TEXT), content_hash (TEXT)

  code_edges:
    id (INTEGER PK), project_id (TEXT), from_symbol_id (INTEGER),
    to_symbol_id (INTEGER), from_name (TEXT), to_name (TEXT),
    edge_type (TEXT: calls/imports), file_path (TEXT), line_number (INTEGER)

  code_projects:
    id (TEXT PK), root_path (TEXT), name (TEXT), file_count (INTEGER),
    symbol_count (INTEGER), last_indexed (TEXT)

Indexes: code_symbols(file_path), code_symbols(symbol_name),
          code_edges(to_name), code_edges(from_symbol_id),
          code_symbols_fts(code_symbols_fts) [FTS5 virtual table]"""

    if uri.startswith("code/project/"):
        project_name = uri[len("code/project/"):]
        projects = find_code_projects()
        for p in projects:
            if p["name"] == project_name:
                from indexer import CodeIndexer
                db_path = os.path.join(p["root"], ".basemem.code.db")
                if os.path.exists(db_path):
                    indexer = CodeIndexer(p["root"])
                    try:
                        stats = indexer.get_project_stats()
                        files = indexer.list_files(limit=0)
                        result = [f"Project: {p['name']}"]
                        result.append(f"  Root: {p['root']}")
                        result.append(f"  Files: {stats.get('file_count', 0)}")
                        result.append(f"  Symbols: {stats.get('symbol_count', 0)}")
                        result.append(f"  Edges: {stats.get('edges', 0)}")
                        result.append(f"  Last indexed: {stats.get('last_indexed', 'unknown')}")
                        result.append(f"  Files indexed: {len(files)}")
                        return "\n".join(result)
                    finally:
                        indexer.close()
                return f"Project '{project_name}' at {p['root']} (no accessible index)"
        return f"Project '{project_name}' not found. Use list_mcp_resources to see available projects."

    return f"Unknown resource URI: {uri}. Use list_mcp_resources to see available URIs."


def main():
    server.run()


if __name__ == "__main__":
    main()
