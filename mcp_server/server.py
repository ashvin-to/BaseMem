"""MCP server for BaseMem."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    """Resolve DB path and ensure schema exists."""
    path = _resolve_db_path()
    _ensure_schema()
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


import os
import sqlite3

from mcp.server.fastmcp import FastMCP

server = FastMCP("basemem-mcp")


def _ensure_schema():
    """Create planets and notes tables if they don't exist."""
    db_path = _resolve_db_path()
    if not os.path.isfile(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS planets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE NOT NULL,
                display_topic TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                goal TEXT DEFAULT '',
                current_state TEXT DEFAULT '',
                next_step TEXT DEFAULT '',
                next_steps TEXT DEFAULT '[]',
                files TEXT DEFAULT '[]',
                commands TEXT DEFAULT '[]',
                handoff TEXT DEFAULT '',
                aliases TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                title TEXT DEFAULT '',
                agent_id TEXT DEFAULT 'default',
                status TEXT DEFAULT 'open',
                turn_index INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
    finally:
        conn.close()



@server.tool(description="Index/refresh project code graph (tree-sitter).")
def code_init(project_root: str) -> str:
    """Index a project's source code into a per-project .basemem.code.db."""
    import os
    if not os.path.isdir(project_root):
        return f"Directory not found: {project_root}"

    from indexer import CodeIndexer
    indexer = CodeIndexer(project_root)
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


@server.tool(description="Find code symbols by name/signature. Single match includes callers/callees. REPLACES grep/glob/Read for code exploration.")
def code_find(
    query: str = "",
    project_root: str = "",
    limit: int = 20,
    use_regex: bool = False,
    dead: bool = False,
    file_path: str = "",
) -> str:
    """Search for code symbols in a project's .basemem.code.db.

    dead=True  — find files never imported by other files (import-chain analysis).
    file_path  — filter results to a specific file (e.g. 'indexer.py').
    """
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not project_root:
        project_root = _detect_project_root()
    db_path = os.path.join(project_root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        _ci = CodeIndexer(project_root)
        try:
            _ci.index_project(max_workers=4)
        finally:
            _ci.close()
    indexer = CodeIndexer(project_root)
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

        # File-level browse mode
        if file_path and (not query or query.strip() in (".", "*", "%", "")):
            results = indexer.list_symbols_by_file(file_path, limit=limit)
            if not results:
                return f"No symbols in '{file_path}'."
            parts = [f"{len(results)} symbol(s) in {file_path}:"]
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
                if file_path:
                    symbols = [s for s in symbols if s['file_path'] == file_path]
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
            return "\n".join(parts)

        results = indexer.search_symbols(query, limit=limit, use_regex=use_regex)
        if file_path:
            results = [r for r in results if r['file_path'] == file_path]
        if results:
            parts = [f"{len(results)} match(es):"]
            for r in results:
                loc = _fmt_loc(r['file_path'])
                sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                parts.append(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
            return "\n".join(parts)

        # Browse fallback — list all symbols grouped by file
        import sqlite3
        _c = indexer.conn
        total = _c.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0]
        files = _c.execute("SELECT COUNT(DISTINCT file_path) FROM code_symbols").fetchone()[0]
        parts = [f"📁 {os.path.basename(project_root)} — {files}f {total}s\n"]
        parts.append(f"No match for '{query}' — browse symbols by file (call code_find with an ID for callers):\n")
        for row in _c.execute("""
            SELECT file_path, id, symbol_name, symbol_type, start_line
            FROM code_symbols
            ORDER BY file_path, start_line
            LIMIT 200
        """):
            if file_path and row['file_path'] != file_path:
                continue
            typemark = "🧩" if row["symbol_type"] in ("function", "method") else "📦"
            parts.append(f"  [{row['id']}] {typemark} {row['symbol_name']} ({row['file_path']}:{row['start_line']})")
        if total > 200:
            parts.append(f"\n  ... and {total - 200} more symbols (be more specific)")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(description="Trace call chain: inbound (callers), outbound (callees), or both, with configurable depth.")
def code_trace(
    symbol_name: str,
    project_root: str = "",
    direction: str = "both",
    depth: int = 2,
    limit: int = 10,
) -> str:
    """Trace call chains: who calls this symbol and what does it call?"""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not project_root:
        project_root = _detect_project_root()
    db_path = os.path.join(project_root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
    indexer = CodeIndexer(project_root)
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

        lines.append(f"Trace: {symbol_name} ({direction}, depth={depth})")
        _trace(symbol_name, 1)
        if len(lines) <= 1:
            return f"{symbol_name}: no call chain found."
        return "\n".join(lines)
    finally:
        indexer.close()


@server.tool(description="Scan for indexed code projects (comma-separated paths).")
def code_list_projects(search_root: str = "") -> str:
    """Scan for all .basemem.code.db files on the system."""
    from indexer.indexer import find_code_projects
    projects = find_code_projects(search_root)
    if not projects:
        return "No projects found."
    parts = [f"{len(projects)} project(s):"]
    for p in sorted(projects, key=lambda x: x["name"]):
        parts.append(f"  {p['name']}: {p['symbols']}s {p['files']}f")
    return "\n".join(parts)


@server.tool(description="Show project file structure from the index with symbol counts per file.")
def code_files(project_root: str = "", prefix: str = "", limit: int = 100) -> str:
    """List indexed files with symbol counts in a project."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not project_root:
        project_root = _detect_project_root()
    db_path = os.path.join(project_root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
    indexer = CodeIndexer(project_root)
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


@server.tool(description="Explore an area: relevant symbols' source + call paths in one shot.")
def code_explore(query: str, project_root: str = "", max_files: int = 3, limit: int = 10) -> str:
    """Search symbols and show their callers/callees + source code."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not project_root:
        project_root = _detect_project_root()
    db_path = os.path.join(project_root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
    indexer = CodeIndexer(project_root)
    try:
        symbols = indexer.search_symbols(query, limit=limit)
        if not symbols:
            return f"No matches for '{query}'."
        parts = []
        shown_files = set()
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
            # Show source
            if sym['file_path'] not in shown_files and len(shown_files) < max_files:
                shown_files.add(sym['file_path'])
                abs_fp = os.path.join(project_root, sym['file_path'])
                if os.path.isfile(abs_fp):
                    with open(abs_fp) as f:
                        lines = f.read().splitlines()
                    start = max(0, sym['start_line'] - 2)
                    end = min(len(lines), sym['end_line'] + 1)
                    parts.append(f"  source ({sym['start_line']}-{sym['end_line']}):")
                    for i in range(start, end):
                        marker = "→" if i == sym['start_line'] - 1 else " "
                        parts.append(f"    {marker} L{i+1}: {lines[i]}")
        return "\n".join(parts) if parts else "No results."
    finally:
        indexer.close()


@server.tool(description="Analyze what code is affected by changing a symbol (transitive reverse deps).")
def code_impact(symbol_name: str, project_root: str = "", depth: int = 2, limit: int = 30) -> str:
    """Trace transitive reverse dependencies for a symbol."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    if not project_root:
        project_root = _detect_project_root()
    db_path = os.path.join(project_root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return f"No code index at {db_path}."
    indexer = CodeIndexer(project_root)
    try:
        results = indexer.get_impact(symbol_name, depth=depth, limit=limit)
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




@server.tool(description="Get structured context for a topic (state, code stats, decisions, facts).")
def get_agent_context(topic: str = "", project: str = "", query: str = "") -> str:
    """Get session context for a topic — always returns something useful."""
    import sqlite3
    from indexer import CODE_DB_FILENAME

    if project and not topic:
        topic = project
    if not topic:
        return "ctx: (unknown)\n  state: Provide `project='folder'` or `topic='name'`."

    lines = [f"ctx: {topic}"]
    q = query.strip().lower()

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        lines.append("  state: (no memory db yet — will be created on first write)")
        return "\n".join(lines)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT OR IGNORE INTO notes (topic, kind, content, agent_id, turn_index) VALUES (?, 'turn', ?, 'system', 0)",
            (topic, f"Context retrieved (query: {query or 'none'})"),
        )
        conn.commit()
    except Exception:
        pass

    try:
        planet = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()

        if planet:
            if planet["current_state"]:
                lines.append(f"  state: {planet['current_state']}")
            if planet["next_step"]:
                lines.append(f"  next: {planet['next_step']}")
        else:
            lines.append("  state: (no context yet)")
            topics = conn.execute(
                "SELECT topic FROM planets WHERE topic LIKE ? LIMIT 5",
                (f"%{topic}%",),
            ).fetchall()
            if topics:
                names = ", ".join(r[0] for r in topics)
                lines.append(f"  (did you mean: {names})")

        limit = 20 if q else 5
        notes = conn.execute(
            "SELECT kind, content FROM notes WHERE topic = ? AND kind IN ('decision','issue','fact') ORDER BY created_at DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
        for n in notes:
            if not q or q in n["content"].lower():
                tag = {"decision": "dec", "issue": "iss", "fact": "fact"}[n["kind"]]
                lines.append(f"  {tag}: {n['content']}")
    finally:
        conn.close()

    try:
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


@server.tool(description="Read full planet details (state, notes, metadata).")
def read_planet(topic: str) -> str:
    """Read all details of a specific planet/topic."""
    import json
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        planet = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()
        if not planet:
            return f"No planet found for topic '{topic}'."

        notes = conn.execute(
            "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 50",
            (topic,),
        ).fetchall()

        display = planet["display_topic"] or planet["topic"]
        next_steps = json.loads(planet["next_steps"] or "[]")
        files = json.loads(planet["files"] or "[]")
        commands = json.loads(planet["commands"] or "[]")

        lines = [f"{display} | {planet['status'] or 'active'}"]
        lines.append(f"  goal: {planet['goal'] or '—'}")
        lines.append(f"  state: {planet['current_state'] or '—'}")
        lines.append(f"  next: {planet['next_step'] or '—'}")
        if next_steps:
            lines.append(f"  steps: {', '.join(next_steps)}")
        if files:
            lines.append(f"  files: {', '.join(files)}")
        if commands:
            lines.append(f"  cmds: {', '.join(commands)}")
        if planet["handoff"]:
            lines.append(f"  handoff: {planet['handoff']}")
        if notes:
            lines.append(f"  notes ({len(notes)}):")
            for n in notes[:10]:
                lines.append(f"    [{n['kind'][:4]}] {n['content'][:200]}")
        return "\n".join(lines)
    finally:
        conn.close()


@server.tool(description="Log an interaction: add note(s), update planet state, log turn — all in one call.")
def log_interaction(
    topic: str,
    decision: str = "",
    fact: str = "",
    summary: str = "",
    current_state: str = "",
    next_step: str = "",
    activity: str = "",
) -> str:
    """Log an interaction: add notes + update planet + log turn in one call."""
    import sqlite3
    import json

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        parts = []
        for kind, val in [("decision", decision), ("fact", fact), ("summary", summary)]:
            if val:
                conn.execute(
                    "INSERT INTO notes (topic, kind, content) VALUES (?, ?, ?)",
                    (topic, kind, val),
                )
                parts.append(f"note({kind})")

        update_cols = {}
        if current_state:
            update_cols["current_state"] = current_state
        if next_step:
            update_cols["next_step"] = next_step

        if update_cols:
            existing = conn.execute(
                "SELECT * FROM planets WHERE topic = ?", (topic,)
            ).fetchone()
            if existing:
                updates = [f"{k} = ?" for k in update_cols]
                params = list(update_cols.values()) + [topic]
                conn.execute(
                    f"UPDATE planets SET {', '.join(updates)} WHERE topic = ?",
                    params,
                )
            else:
                conn.execute(
                    "INSERT INTO planets (topic, current_state, next_step, status, next_steps) VALUES (?, ?, ?, 'active', '[]')",
                    (topic, update_cols.get("current_state", ""), update_cols.get("next_step", "")),
                )
            parts.append("planet_updated")

        if activity:
            conn.execute(
                "INSERT INTO notes (topic, kind, content) VALUES (?, 'turn', ?)",
                (topic, activity),
            )
            parts.append("turn_logged")

        conn.commit()
        return f"{' + '.join(parts) if parts else 'no changes'} for '{topic}'."
    finally:
        conn.close()


@server.tool(description="Update or create a planet (state, next_step, goal, files, etc).")
def update_planet(
    topic: str,
    current_state: str = "",
    next_step: str = "",
    status: str = "",
    goal: str = "",
    file_path: str = "",
    command: str = "",
    handoff: str = "",
) -> str:
    """Update or create a planet with all supported fields."""
    import sqlite3
    import json

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()

        fields = {
            "current_state": current_state,
            "next_step": next_step,
            "status": status,
            "goal": goal,
            "handoff": handoff,
        }

        if existing:
            updates = []
            params = []
            for col, val in fields.items():
                if val:
                    updates.append(f"{col} = ?")
                    params.append(val)

            if file_path:
                files = set(json.loads(existing["files"] or "[]"))
                files.add(file_path)
                updates.append("files = ?")
                params.append(json.dumps(sorted(files)))

            if command:
                commands = set(json.loads(existing["commands"] or "[]"))
                commands.add(command)
                updates.append("commands = ?")
                params.append(json.dumps(sorted(commands)))

            if next_step:
                steps = set(json.loads(existing["next_steps"] or "[]"))
                steps.add(next_step)
                updates.append("next_steps = ?")
                params.append(json.dumps(sorted(steps)))

            if updates:
                params.append(topic)
                conn.execute(
                    f"UPDATE planets SET {', '.join(updates)} WHERE topic = ?",
                    params,
                )
        else:
            next_steps_set = set()
            if next_step:
                next_steps_set.add(next_step)
            files_set = set()
            if file_path:
                files_set.add(file_path)
            commands_set = set()
            if command:
                commands_set.add(command)

            conn.execute(
                "INSERT INTO planets (topic, current_state, next_step, status, goal, files, commands, handoff, next_steps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    topic,
                    current_state or "",
                    next_step or "",
                    status or "active",
                    goal or "",
                    json.dumps(sorted(files_set)),
                    json.dumps(sorted(commands_set)),
                    handoff or "",
                    json.dumps(sorted(next_steps_set)),
                ),
            )
        conn.commit()
        return f"Planet '{topic}' updated."
    finally:
        conn.close()





@server.tool(description="Get raw notes for agent-driven summarization.")
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


@server.tool(description="List all available planets/topics.")
def list_planets() -> str:
    """List all topics/planets available in the knowledge base."""
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        planets = conn.execute(
            "SELECT topic, display_topic, status, goal, current_state FROM planets ORDER BY topic"
        ).fetchall()
        if not planets:
            return "No planets found. Create one with update_planet."
        lines = ["# Available Planets"]
        for p in planets:
            name = p["display_topic"] or p["topic"]
            status_tag = f" [{p['status']}]" if p["status"] and p["status"] != "active" else ""
            lines.append(f"- {name}{status_tag}")
        return "\n".join(lines)
    finally:
        conn.close()


@server.tool(description="Full-text search across planets, notes, and nodes.")
def search_nodes(query: str, limit: int = 10) -> str:
    """Full-text search across planets, notes, and nodes."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        like = f"%{query}%"
        lines = [f"# Search results for: '{query}'\n"]
        count = 0

        # Planets
        for r in conn.execute(
            "SELECT topic, display_topic, current_state FROM planets WHERE topic LIKE ? OR display_topic LIKE ? OR current_state LIKE ? OR goal LIKE ?",
            (like, like, like, like),
        ):
            if count >= limit:
                break
            name = r["display_topic"] or r["topic"]
            preview = (r["current_state"] or "")[:200]
            lines.append(f"🪐 **Planet: {name}**")
            if preview:
                lines.append(f"   {preview}")
            lines.append("")
            count += 1

        # Notes
        for r in conn.execute(
            "SELECT topic, kind, content FROM notes WHERE content LIKE ? OR title LIKE ?",
            (like, like),
        ):
            if count >= limit:
                break
            preview = (r["content"] or "")[:200]
            lines.append(f"[note] **{r['topic']} [{r['kind']}]**")
            lines.append(f"   {preview}")
            lines.append("")
            count += 1

        # Old nodes
        from storage.db import StorageManager
        storage = StorageManager(db_path)
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
        storage.close()

        if count == 0:
            return "No matches found."

        return "\n".join(lines)
    finally:
        conn.close()


@server.tool(description="Search notes by topic, kind, and text.")
def search_notes(topic: str, kind: str = "", query: str = "", limit: int = 10) -> str:
    """Search notes by topic, kind, and text."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, topic, kind, content, created_at FROM notes WHERE topic = ?"
        params: list[str | int] = [topic]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        if query:
            query_lower = query.lower()
            rows = [r for r in rows if query_lower in (r["content"] or "").lower()]

        if not rows:
            return "No matching notes found."

        lines = [f"# Notes for '{topic}'" + (f" (kind: {kind})" if kind else "")]
        for r in rows:
            preview = (r["content"] or "")[:200]
            lines.append(
                f"\n**[{r['kind'].upper()}] (id={r['id']})**\n{preview}"
            )
        return "\n".join(lines)
    finally:
        conn.close()


@server.tool(description="Read a full node by its ID.")
def get_node(node_id: str) -> str:
    """Read a full node by its ID."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, topic, content, created_at, updated_at FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            return f"No node found with id '{node_id}'."

        return (
            f"**ID:** {row['id']}\n"
            f"**Topic:** {row['topic']}\n"
            f"**Created:** {row['created_at']}\n"
            f"**Updated:** {row.get('updated_at', 'N/A')}\n"
            f"\n**Content:**\n{row['content']}"
        )
    finally:
        conn.close()


@server.tool(description="Link two notes with a type and weight.")
def link_notes(from_note_id: str, to_note_id: str, link_type: str = "related", weight: float = 1.0) -> str:
    """Link two notes together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_notes(from_note_id, to_note_id, link_type, weight)
    return msg


@server.tool(description="Find notes connected to a given note.")
def get_note_neighbors(note_id: str) -> str:
    """Get neighbors of a note."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    neighbors = manager.get_note_neighbors(note_id)
    if not neighbors:
        return "No linked notes found."
    lines = [f"Neighbors of {note_id}:\n"]
    for n in neighbors:
        name = n["title"] or n["content"][:80]
        lines.append(f"- note-{n['id']} [{n['link_type']}] (w={n['weight']}) {name}")
    return "\n".join(lines)


# ── Planet links ─────────────────────────────────────────────


@server.tool(description="Link two planets with a relation type.")
def link_planets(from_planet: str, to_planet: str, relation: str = "related", weight: float = 1.0) -> str:
    """Link two planets together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_planets(from_planet, to_planet, relation, weight)
    return msg


@server.tool(description="Get planets linked to a given planet.")
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


@server.tool(description="Set memory state: hot, warm, or compacted.")
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
def get_neighbors_weighted(note_id: str, depth: int = 1, min_weight: float = 0.0) -> str:
    """Weighted neighbor traversal with configurable depth."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    results = manager.get_neighbors_weighted(nid, depth=depth, min_weight=min_weight)
    if not results:
        return "No neighbors found at this depth."
    lines = [f"Neighbors (depth={depth}, min_weight={min_weight}):\n"]
    for r in results:
        lines.append(f"  note-{r['id']} [{r['link_type']}] (w={r['weight']}, d={r['_depth']}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines)


@server.tool(description="Extract weighted subgraph as JSON.")
def get_subgraph(note_id: str, depth: int = 2, min_weight: float = 0.2) -> str:
    """Extract weighted subgraph around a note."""
    import json
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    result = manager.get_subgraph(nid, depth=depth, min_weight=min_weight)
    return json.dumps(result, indent=2)


@server.tool(description="Rank neighbors by weight or confidence.")
def rank_neighbors(note_id: str, by: str = "weight") -> str:
    """Rank neighbors by weight or confidence."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    ranked = manager.rank_neighbors(nid, by=by)
    if not ranked:
        return "No neighbors found."
    lines = [f"Neighbors ranked by {by}:\n"]
    for i, r in enumerate(ranked, 1):
        lines.append(f"  {i}. note-{r['id']} (w={r['weight']}, c={r.get('confidence','?')}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines)


# ── Graph-aware retrieval (continued) ─────────────────────────


@server.tool(description="Return two notes for agent similarity comparison.")
def compute_similarity(note_id_a: str, note_id_b: str) -> str:
    """Return both notes for agent-driven semantic similarity comparison."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid_a = manager._parse_note_id(note_id_a)
    nid_b = manager._parse_note_id(note_id_b)
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


@server.tool(description="Return notes for agent-driven reordering.")
def rerank(query: str, note_ids: list) -> str:
    """Return query + note contents for agent-driven reranking."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ids = []
    for nid in note_ids:
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

def main():
    server.run()


if __name__ == "__main__":
    main()
