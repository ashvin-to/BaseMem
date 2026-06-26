"""MCP server for BaseMem."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    """Resolve DB path and ensure schema exists."""
    path = _resolve_db_path()
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    from storage.sessions import _ensure_schema as _ensure_all_schema
    conn = sqlite3.connect(path)
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

from mcp.server.fastmcp import FastMCP

server = FastMCP("mem")




@server.tool(description="Index project code (tree-sitter). Auto-runs on first code_find.")
def code_init(projectRoot: str) -> str:
    """Index a project's source code into a per-project .basemem.code.db."""
    import os
    if not os.path.isdir(projectRoot):
        return f"Directory not found: {projectRoot}"

    from indexer import CodeIndexer
    indexer = CodeIndexer(projectRoot)
    try:
        result = indexer.index_project(max_workers=4)
        return (
            f"Indexed {result['files']} files, {result['symbols']} symbols, "
            f"{result['edges']} edges in {result['elapsed']:.1f}s\n"
            f"DB: {indexer.db_path}"
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


@server.tool(description="Find code symbols. grep=True = raw text search across ALL files. references=True = find all usages across indexed files. REPLACES grep.")
def code_find(
    query: str = "",
    projectRoot: str = "",
    limit: int = 20,
    useRegex: bool = False,
    dead: bool = False,
    filePath: str = "",
    source: bool = False,
    references: bool = False,
    grep: bool = False,
) -> str:
    """Search for code symbols. Single match = detail + callers/callees + source.
       Empty query = file overview.
       filePath='indexer.py' = filter to file.
       dead=True = find files never imported by other files.
       source=True = include source code lines (for edit workflow: code_find → edit).
       references=True = find all references/occurrences across indexed files.
       grep=True = raw ripgrep search across ALL files (non-code too), replaces native grep.
    """
    import os

    # Grep mode — raw text search across all files via ripgrep (no indexer needed)
    if grep and query:
        import subprocess
        cmd = ["rg", "-n", "--no-heading"]
        if useRegex:
            cmd.append("--regexp")
        else:
            cmd.extend(["--fixed-strings"])
        if filePath:
            cmd.extend(["--glob", filePath])
        cmd.extend([query, projectRoot])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode not in (0, 1):
                return f"grep error: {result.stderr.strip()}"
            if not result.stdout.strip():
                return f"No matches for '{query}'."
            lines = result.stdout.strip().splitlines()
            shown = lines[:limit]
            parts = [f"{len(lines)} match(es) for '{query}':"]
            for line in shown:
                parts.append(f"  {line}")
            if len(lines) > limit:
                parts.append(f"  ... and {len(lines) - limit} more")
            return "\n".join(parts)
        except FileNotFoundError:
            return "ripgrep (rg) not found. Install it or use references=True for indexed files."
        except subprocess.TimeoutExpired:
            return f"Search timed out for '{query}'."

    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        _ci = CodeIndexer(projectRoot)
        try:
            _ci.index_project(max_workers=4)
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
            parts = [f"{sym['symbol_name']} ({loc}) {sym['language']}"]
            if sym.get('signature'):
                parts.append(f"  sig: {sym['signature']}")
            if sym.get('docstring'):
                parts.append(f"  doc: {sym['docstring'][:200]}")
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10])
                parts.append(f"  callers: {cstr}")
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
                parts.append(f"  calls: {cstr}")
            if source:
                abs_fp = os.path.join(projectRoot, sym['file_path'])
                if os.path.isfile(abs_fp):
                    with open(abs_fp) as _f:
                        lines = _f.read().splitlines()
                    start = max(0, sym['start_line'] - 1)
                    end = min(len(lines), sym['end_line'])
                    parts.append(f"  source ({sym['start_line']}:{sym['end_line']}):")
                    for i in range(start, end):
                        parts.append(f"    L{i+1}: {lines[i]}")
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

        # Browse fallback — show file overview with symbol counts
        import sqlite3
        _c = indexer.conn
        total = _c.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0]
        files = _c.execute("SELECT COUNT(DISTINCT file_path) FROM code_symbols").fetchone()[0]
        parts = [f"{os.path.basename(projectRoot)} — {files}f {total}s"]
        parts.append(f"No match for '{query}' — show files (use code_find(filePath=...) or code_find('sym') to drill in):\n")
        for row in _c.execute("""
            SELECT file_path, COUNT(*) as cnt, MAX(symbol_type) as type
            FROM code_symbols GROUP BY file_path ORDER BY file_path
            LIMIT 100
        """):
            if file_path and row['file_path'] != file_path:
                continue
            parts.append(f"  {row['file_path']} ({row['cnt']} sym)")
        if files > 100:
            parts.append(f"\n  ... and {files - 100} more files (use prefix filter)")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(description="Trace call chain: who calls this symbol and what does it call?")
def code_trace(
    symbolName: str,
    projectRoot: str = "",
    direction: str = "both",
    depth: int = 2,
    limit: int = 10,
) -> str:
    """Trace call chains: who calls this symbol and what does it call?"""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
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
                        lines.append(f"{prefix}  <- {c['symbol_name']} ({loc}:{c['line_number']})")
                        _trace(c['symbol_name'], d + 1, prefix + "    ")
            if direction in ("outbound", "both"):
                callees = indexer.get_callees(name)
                if callees:
                    for c in callees[:limit]:
                        loc = _fmt_loc(c['file_path'])
                        lines.append(f"{prefix}  -> {c['to_name']} ({loc}:{c['line_number']})")
                        _trace(c['to_name'], d + 1, prefix + "    ")

        lines.append(f"Trace: {symbolName} ({direction}, depth={depth})")
        _trace(symbolName, 1)
        if len(lines) <= 1:
            return f"{symbolName}: no call chain found."
        return "\n".join(lines)
    finally:
        indexer.close()


@server.tool(description="Scan for indexed code projects.")
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


@server.tool(description="Show project files. pattern='**/*.json' = glob wildcard search. Use prefix='src/' to filter indexed files.")
def code_files(projectRoot: str = "", prefix: str = "", pattern: str = "", limit: int = 100) -> str:
    """List indexed files with symbol counts, or glob files by pattern. Replaces native glob."""
    import os
    import glob as _glob
    if pattern:
        if not projectRoot:
            projectRoot = _detect_project_root()
        matches = sorted(_glob.glob(os.path.join(projectRoot, pattern), recursive=True))
        if not matches:
            return f"No files matching '{pattern}'."
        rels = [os.path.relpath(m, projectRoot) for m in matches]
        parts = [f"{len(rels)} file(s) matching '{pattern}':"]
        for r in rels[:limit]:
            parts.append(f"  {r}")
        if len(rels) > limit:
            parts.append(f"  ... and {len(rels) - limit} more")
        return "\n".join(parts)

    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {projectRoot}."
    indexer = CodeIndexer(projectRoot)
    try:
        files = indexer.list_files(prefix=prefix, limit=limit)
        if not files:
            return "No files in index."
        parts = [f"{len(files)} file(s):"]
        for f in files:
            parts.append(f"  {f['file_path']} ({f['symbol_count']}s)")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(description="Explore: view source + call paths in one shot. Use symbol name from code_find.")
def code_explore(query: str, projectRoot: str = "", limit: int = 10) -> str:
    """View source code and callers/callees for a symbol or area.
    Tries exact symbol name/ID first, then full-text search.
    """
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
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
                # Multiple exact matches — prefer the one with most context
                symbols = exact[:limit]

        if not symbols:
            symbols = indexer.search_symbols(query, limit=limit)
        if not symbols:
            return f"No matches for '{query}'."
        parts = []
        for sym in symbols[:limit]:
            loc = _fmt_loc(sym['file_path'])
            parts.append(f"\n── {sym['symbol_name']} ({loc}) {sym['symbol_type']} ──")
            if sym.get('signature'):
                parts.append(f"  sig: {sym['signature']}")
            callers = indexer.get_callers(sym['symbol_name'])
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:5])
                parts.append(f"  callers: {cstr}")
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:5])
                parts.append(f"  calls: {cstr}")
            # Show source — always show for the matched symbol
            abs_fp = os.path.join(projectRoot, sym['file_path'])
            if os.path.isfile(abs_fp):
                with open(abs_fp) as f:
                    lines = f.read().splitlines()
                start = max(0, sym['start_line'] - 1)
                end = min(len(lines), sym['end_line'])
                parts.append(f"  source ({sym['start_line']}:{sym['end_line']}):")
                for i in range(start, end):
                    marker = "->" if i == sym['start_line'] - 1 else "  "
                    parts.append(f"    {marker} L{i+1}: {lines[i]}")
        return "\n".join(parts) if parts else "No results."
    finally:
        indexer.close()


@server.tool(description="Analyze impact of changing a symbol (transitive reverse deps).")
def code_impact(symbolName: str, projectRoot: str = "", depth: int = 2, limit: int = 30) -> str:
    """Trace transitive reverse dependencies for a symbol."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
    indexer = CodeIndexer(projectRoot)
    try:
        results = indexer.get_impact(symbolName, depth=depth, limit=limit)
        if not results:
            return f"No impact found for '{symbol_name}'."
        parts = [f"Impact analysis for '{symbol_name}' (depth={depth}):"]
        for r in results:
            loc = _fmt_loc(r['file_path'])
            via = f" (via {r['via']})" if r.get('via') else ""
            parts.append(f"  [{r['id']}] {r['symbol_name']} ({loc}:{r['line_number']}){via}")
        return "\n".join(parts)
    finally:
        indexer.close()


# ── End Code Graph Tools ──────────────────────────────────────────




@server.tool(description="CALL FIRST — load session memory: state, decisions, facts, code stats.")
def getContext(topic: str = "", project: str = "", query: str = "") -> str:
    """Call at session start to load past state, decisions, facts for a topic."""
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


@server.tool(description="Full planet details: state, notes, files, commands.")
def read_planet(topic: str) -> str:
    """Read all details of a specific planet/topic."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager, _get_notes

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
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


@server.tool(description="Persist session: decisions, facts, state, activity — all in one call.")
def log_interaction(
    topic: str,
    decision: str = "",
    fact: str = "",
    summary: str = "",
    currentState: str = "",
    nextStep: str = "",
    activity: str = "",
) -> str:
    """Log an interaction: add notes + update planet + log turn in one call. Call during session for decisions/facts and at session end for summary."""
    from storage.db import StorageManager
    from storage.sessions import SessionManager

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
        manager.log_chat_to_planet(topic, topic, activity, agent_id="system", sender="system")
        parts.append("turn_logged")

    return f"{' + '.join(parts) if parts else 'no changes'} for '{topic}'."


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
    """Update or create a planet with all supported fields."""
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





@server.tool(description="Get raw notes for agent summarization.")
def summarize_planet(topic: str, limit: int = 50) -> str:
    """Return all notes for a planet formatted for agent summarization."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    return manager.summarize_planet(topic, limit=limit)


@server.tool(description="Trim old notes, keep summaries + 30 recent.")
def compact_planet(topic: str) -> str:
    """Compact a planet - keep summaries + 30 recent notes, delete the rest."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    count_before = manager.get_note_count(topic)
    proxy = manager.compact_planet("default", topic)
    count_after = manager.get_note_count(topic)
    return f"Compacted '{topic}': {count_before} notes -> {count_after} notes kept."


@server.tool(description="List all planets/topics.")
def list_planets() -> str:
    """List all topics/planets available in the knowledge base."""
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


@server.tool(description="Full-text search across planets, notes, nodes.")
def search_nodes(query: str, limit: int = 10) -> str:
    """Full-text search across planets, notes, and nodes."""
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
def search_notes(topic: str, kind: str = "", query: str = "", limit: int = 10) -> str:
    """Search notes by topic, kind, and text."""
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


@server.tool(description="Read a full node by ID.")
def get_node(nodeId: str) -> str:
    """Read a full node by its ID."""
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


@server.tool(description="Link two notes with type and weight.")
def link_notes(fromNoteId: str, toNoteId: str, linkType: str = "related", weight: float = 1.0) -> str:
    """Link two notes with a typed relationship. Valid types: related, depends, implements, fixes, duplicates, supersedes, causes, blocks, tests, references"""
    """Link two notes together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_notes(fromNoteId, toNoteId, linkType, weight)
    return msg


@server.tool(description="Find notes linked to a note.")
def get_note_neighbors(noteId: str) -> str:
    """Get neighbors of a note."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    neighbors = manager.get_note_neighbors(noteId)
    if not neighbors:
        return "No linked notes found."
    lines = [f"Neighbors of {noteId}:\n"]
    for n in neighbors:
        name = n["title"] or n["content"][:80]
        lines.append(f"- note-{n['id']} [{n['link_type']}] (w={n['weight']}) {name}")
    return "\n".join(lines)


@server.tool(description="Pin a note so compact_planet never drops it.")
def note_pin(noteId: str) -> str:
    """Pin a note to preserve it through compaction."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.pin_note(noteId)
    return msg


@server.tool(description="Unpin a note.")
def note_unpin(noteId: str) -> str:
    """Unpin a previously pinned note."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.unpin_note(noteId)
    return msg


@server.tool(description="Set tags on a note (replaces existing tags).")
def note_tag(noteId: str, tags: str) -> str:
    """Tag a note with comma-separated keywords."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ok, msg = manager.tag_note(noteId, tag_list)
    return msg


# ── Task MCP tools ─────────────────────────────────────────────


@server.tool(description="Create a task on a planet. Returns the task id.")
def task_create(topic: str, title: str, priority: str = "medium", depends_on: list | None = None, files: list | None = None, notes: list | None = None) -> str:
    """Create a new task on a planet with status=todo."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.create_task(topic, title, priority=priority, depends_on=depends_on, files=files, notes=notes)
    deps = json.loads(result.get("depends_on", "[]"))
    parts = [f"Task created: task-{result['id']} [{result['status']}/{result['priority']}] {result['title']}"]
    if deps:
        parts.append(f"  depends_on: {deps}")
    return "\n".join(parts)


@server.tool(description="Update a task's status, priority, files, or notes.")
def task_update(task_id: int, status: str | None = None, priority: str | None = None, files: list | None = None, notes: list | None = None) -> str:
    """Update task fields: status, priority, files, notes."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.update_task(task_id, status=status, priority=priority, files=files, notes=notes)
    return msg


@server.tool(description="List tasks, optionally filtered by topic, status, priority.")
def task_list(topic: str | None = None, status: str | None = None, priority: str | None = None) -> str:
    """List tasks with optional filters."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
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
    """Mark a task as blocked. If reason is given, creates a linked issue note."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
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
                manager.update_task(task_id, notes=existing)
    ok, msg = manager.update_task(task_id, status="blocked")
    return "Blocked. " + msg if ok else msg


# ── Planet links ─────────────────────────────────────────────


@server.tool(description="Link two planets with a relation type.")
def link_planets(fromPlanet: str, toPlanet: str, relation: str = "related", weight: float = 1.0) -> str:
    """Link two planets together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_planets(fromPlanet, toPlanet, relation, weight)
    return msg


@server.tool(description="Get planets linked to a planet.")
def get_planet_links(planet: str) -> str:
    """Get planets linked to the given planet."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    links = manager.get_planet_links(planet)
    if not links:
        return f"No planet links found for '{planet}'."
    lines = [f"Planets linked to '{planet}':\n"]
    for l in links:
        lines.append(f"- {l['planet']} [{l['relation']}] (w={l['weight']})")
    return "\n".join(lines)


# ── Memory tiers ──────────────────────────────────────────────


@server.tool(description="Set memory tier: hot, warm, compacted.")
def set_memory_state(topic: str, state: str) -> str:
    """Set memory tier for a planet."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.set_memory_state(topic, state)
    return msg


# ── Graph-aware retrieval ─────────────────────────────────────


@server.tool(description="Weighted neighbor traversal with depth.")
def get_neighbors_weighted(noteId: str, depth: int = 1, minWeight: float = 0.0) -> str:
    """Weighted neighbor traversal with configurable depth."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(noteId)
    if nid is None:
        return f"Invalid note ID: {noteId}"
    results = manager.get_neighbors_weighted(nid, depth=depth, min_weight=minWeight)
    if not results:
        return "No neighbors found at this depth."
    lines = [f"Neighbors (depth={depth}, min_weight={minWeight}):\n"]
    for r in results:
        lines.append(f"  note-{r['id']} [{r['link_type']}] (w={r['weight']}, d={r['_depth']}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines)


@server.tool(description="Extract weighted subgraph as JSON.")
def get_subgraph(noteId: str, depth: int = 2, minWeight: float = 0.2) -> str:
    """Extract weighted subgraph around a note."""
    import json
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(noteId)
    if nid is None:
        return f"Invalid note ID: {noteId}"
    result = manager.get_subgraph(nid, depth=depth, min_weight=minWeight)
    return json.dumps(result, indent=2)


@server.tool(description="Rank neighbors by weight or confidence.")
def rank_neighbors(noteId: str, by: str = "weight") -> str:
    """Rank neighbors by weight or confidence."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(noteId)
    if nid is None:
        return f"Invalid note ID: {noteId}"
    ranked = manager.rank_neighbors(nid, by=by)
    if not ranked:
        return "No neighbors found."
    lines = [f"Neighbors ranked by {by}:\n"]
    for i, r in enumerate(ranked, 1):
        lines.append(f"  {i}. note-{r['id']} (w={r['weight']}, c={r.get('confidence','?')}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines)


# ── Graph-aware retrieval (continued) ─────────────────────────


@server.tool(description="Two notes for agent similarity comparison.")
def compute_similarity(noteIdA: str, noteIdB: str) -> str:
    """Return both notes for agent-driven semantic similarity comparison."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
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


@server.tool(description="Notes + query for agent reranking.")
def rerank(query: str, noteIds: list) -> str:
    """Return query + note contents for agent-driven reranking."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
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


@server.tool(description="Decay auto-link weights by a factor.")
def edge_decay(factor: float = 0.9, planet: str | None = None) -> str:
    """Apply weight decay to auto-links."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.edge_decay(factor=factor, planet=planet)
    return f"Decayed {result['decayed']} edge(s) by factor {result['factor']}."


@server.tool(description="Prune edges below a weight threshold.")
def edge_prune(threshold: float = 0.05, planet: str | None = None) -> str:
    """Remove auto-links below weight threshold."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.edge_prune(threshold=threshold, planet=planet)
    return f"Pruned {result['pruned']} edge(s) below threshold {result['threshold']}."


# ── Code Graph MCP Tools ─────────────────────────────────

@server.tool(description="Read file contents with line numbers. offset=start line, limit=max lines.")
def code_read(filePath: str, projectRoot: str = "", offset: int = 0, limit: int = 200) -> str:
    """Read a file from the indexed project. Replaces native Read tool.
       offset (1-indexed): start line. limit: max lines. 0 = all lines.
       Path traversal is prevented — must be within the project."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not projectRoot:
        projectRoot = _detect_project_root()
    db_path = os.path.join(projectRoot, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {projectRoot}."

    # Resolve filePath relative to projectRoot and prevent traversal
    abs_fp = os.path.normpath(os.path.join(projectRoot, filePath))
    abs_root = os.path.normpath(projectRoot)
    if not abs_fp.startswith(abs_root + os.sep) and abs_fp != abs_root:
        return f"File is outside project root: {filePath}"

    if not os.path.isfile(abs_fp):
        return f"File not found: {filePath}"

    try:
        with open(abs_fp, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading {filePath}: {e}"

    total = len(lines)
    start = offset - 1 if offset > 0 else 0
    end = start + limit if limit > 0 else total
    if start > total:
        return f"Offset {offset} exceeds file length ({total} lines)."
    if end > total:
        end = total

    parts = [f"--- {filePath} ({total} lines)"]
    for i in range(start, end):
        parts.append(f"  L{i+1}: {lines[i].rstrip()}")
    if end < total:
        parts.append(f"  ... {total - end} more lines")
    return "\n".join(parts)


def main():
    server.run()


if __name__ == "__main__":
    main()
