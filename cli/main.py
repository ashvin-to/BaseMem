"""Main CLI entry point — registers all subcommand groups."""

import json
import logging
import sqlite3
import sys
from pathlib import Path

import click

from storage.db import StorageManager

from .code import code
from .edge import edge
from .note import note
from .planet import planet
from .session import session
from .task import task

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def get_project_root():
    """Find the nearest project root (folder with AGENTS.md, .git, or fallback to current)"""
    curr = Path.cwd().absolute()
    for parent in [curr] + list(curr.parents):
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent.name
    return curr.name


def _topic_from_cwd():
    """Derive topic from cwd: package.json name → pyproject.toml name → dir name."""
    import os
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents)[:3]:
        pkg = parent / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                if data.get("name"):
                    return data["name"]
            except Exception:
                pass
        pyproj = parent / "pyproject.toml"
        if pyproj.exists():
            try:
                import re
                match = re.search(r'^name\s*=\s*"([^"]+)"', pyproj.read_text(), re.M)
                if match:
                    return match.group(1)
            except Exception:
                pass
    return None


@click.group(name='mem')
@click.option('--db', help='Database path')
@click.pass_context
def cli(ctx, db):
    """BaseMem: AI Knowledge Base Ledger"""
    ctx.ensure_object(dict)
    ctx.obj['db'] = db or str(Path.home() / ".basemem" / "basemem.db")
    ctx.obj['storage'] = StorageManager(ctx.obj['db'])

cli.add_command(session)
cli.add_command(planet)
cli.add_command(note)
cli.add_command(task)
cli.add_command(edge)
cli.add_command(code)


def _read_injected_exclude_ids(topic: str, cache_dir: str | None = None) -> set[int]:
    """Read note ids surfaced by the most recent `mem agent-context` for a topic.

    Mirrors SessionManager.normalize_topic so slugs match the write side in
    storage/notes.py#_write_injected_notes_cache. Missing/corrupt file → empty
    set; never raises.
    """
    from storage.sessions import SessionManager as _SM
    import json as _json
    import os as _os
    try:
        slug = _SM.normalize_topic(topic)
        if cache_dir is None:
            override = _os.environ.get("BASEMEM_INJECTED_DIR")
            base = override or _os.path.join(
                _os.path.expanduser("~"), ".basemem", "injected-notes"
            )
        else:
            base = cache_dir
        p = _os.path.join(base, f"{slug}.json")
        if not _os.path.isfile(p):
            return set()
        with open(p, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return {int(i) for i in (data.get("note_ids") or [])}
    except Exception:
        return set()


# ── Top-level commands ──

@cli.command("viz")
@click.option('--port', '-p', default=5000, help='Port to run visualization web server (default: 5000)')
@click.option('--host', default='127.0.0.1', help='Host interface (default: 127.0.0.1)')
@click.pass_context
def viz_command(ctx, port, host):
    """Launch the BaseMem visualization web server."""
    base = Path(__file__).parent.parent.absolute()
    server_script = base / "server.py"
    if not server_script.exists():
        click.echo("Error: server.py not found.", err=True)
        sys.exit(1)
    python_bin = sys.executable
    click.echo(f"Starting BaseMem visualization web server at http://{host}:{port}...")
    import subprocess
    env = os.environ.copy()
    if ctx.obj.get('db'):
        env['BASEMEM_DB_PATH'] = ctx.obj['db']
    try:
        subprocess.run([python_bin, str(server_script)], env=env)
    except KeyboardInterrupt:
        click.echo("\nServer stopped.")

@cli.command("log")
@click.argument('message', required=False)
@click.option('--topic', '-t', help='Topic/planet name')
@click.option('--message', '-m', 'msg_opt', help='Note message')
@click.pass_context
def log_command(ctx, message, topic, msg_opt):
    """Log an interaction decision or note directly to a planet."""
    text = message or msg_opt
    if not text:
        click.echo("Error: Please provide a message.", err=True)
        sys.exit(2)
    top = topic or _topic_from_cwd() or get_project_root()
    from storage.sessions import SessionManager
    sm = SessionManager(ctx.obj['storage'])
    res = sm.add_note(top, top, "decision", text)
    n_id = res.get("id") if isinstance(res, dict) else res
    click.echo(f"[ok] Note added to '{top}': {text[:80]} ({n_id})")

@cli.command("list-planets")
@click.pass_context
def list_planets(ctx):
    """List all planets in the knowledge base."""
    conn = sqlite3.connect(ctx.obj['db'])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT topic, display_topic, status, goal, current_state FROM planets ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    if not rows:
        click.echo("No planets found.")
        return
    for r in rows:
        name = r["display_topic"] or r["topic"]
        status = r["status"] or "active"
        goal = r["goal"] or ""
        state = r["current_state"] or ""
        tag = f" [{status}]" if status != "active" else ""
        click.echo(f"  {name}{tag}")
        if goal:
            click.echo(f"    Goal: {goal[:120]}")
        if state:
            click.echo(f"    State: {state[:120]}")
        click.echo("")


@cli.command()
@click.argument('query')
@click.pass_context
def search(ctx, query):
    """Search planets, notes, and nodes across the knowledge base."""
    conn = sqlite3.connect(ctx.obj['db'])
    conn.row_factory = sqlite3.Row
    click.echo(f"Searching for: '{query}'...")

    like = f"%{query}%"
    results = []

    for r in conn.execute(
        (
            "SELECT topic, display_topic, current_state, goal, updated_at FROM planets "
            "WHERE topic LIKE ? OR display_topic LIKE ? OR current_state LIKE ? OR goal LIKE ?"
        ),
        (like, like, like, like),
    ):
        name = r["display_topic"] or r["topic"]
        preview = (r["current_state"] or r["goal"] or "")[:150].replace("\n", " ").strip()
        results.append(("planet", name, f"planet-{r['topic']}", preview))

    for r in conn.execute(
        "SELECT id, topic, kind, content, created_at FROM notes WHERE content LIKE ? OR title LIKE ?",
        (like, like),
    ):
        preview = r["content"][:150].replace("\n", " ").strip()
        label = f"{r['topic']} / {r['kind']}"
        results.append(("note", label, f"note-{r['id']}", preview))
    conn.close()

    storage = ctx.obj['storage']
    old_ids = storage.search_nodes_fts(query)
    for nid in old_ids:
        n = storage.get_node(nid)
        if n:
            preview = n.content[:150].replace("\n", " ").strip()
            results.append(("node", n.title, n.id, preview))

    if not results:
        click.echo("No matches found.")
        return

    click.echo(f"Found {len(results)} matches:\n")
    for kind, title, _rid, preview in results:
        tag = {"planet": "[planet]", "note": "[note]", "node": "o"}.get(kind, "*")
        click.echo(f"  {tag} [{kind}] {title}")
        if preview:
            click.echo(f"      {preview}")
    click.echo("")


@cli.command("agent-context")
@click.option('--topic', '-t', help='Topic to load. Defaults to the active planet or current folder.')
@click.option('--query', '-q', help='Optional query to pull extra relevant notes.')
@click.pass_context
def agent_context(ctx, topic, query):
    """Emit a compact prompt block for an agent to read before answering."""
    from storage.sessions import SessionManager

    root_name = get_project_root()
    manager = SessionManager(ctx.obj['storage'])
    resolved_topic = topic

    if not resolved_topic:
        # Derive from cwd: package.json name → pyproject.toml name → dir name
        resolved_topic = _topic_from_cwd() or root_name

    click.echo(manager.build_agent_context(resolved_topic, query=query))


@cli.command()
@click.option('--tokens', is_flag=True, help='Print token budget report')
@click.pass_context
def stats(ctx, tokens):
    """Show database statistics or token budget report."""
    if not tokens:
        click.echo("Run mem stats --tokens for a full token budget report.")
        return

    import asyncio
    import os
    import subprocess
    from pathlib import Path

    # 1. Injection sizes — derive topic from cwd (same logic as fetchContext)
    storage = ctx.obj['storage']

    cwd = Path.cwd()
    topic = cwd.name
    for parent in [cwd] + list(cwd.parents)[:3]:
        pkg_path = parent / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                if pkg.get("name"):
                    topic = pkg["name"]
                    break
            except Exception:
                pass
        pyproject_path = parent / "pyproject.toml"
        if pyproject_path.exists():
            try:
                import re as _re
                content = pyproject_path.read_text()
                match = _re.search(r'^name\s*=\s*"([^"]+)"', content, _re.M)
                if match:
                    topic = match.group(1)
                    break
            except Exception:
                pass

    is_cold_start = False
    mem_ctx_tokens = 0
    try:
        from storage.sessions import SessionManager
        mgr_stats = SessionManager(storage)
        out = mgr_stats.build_agent_context(topic, query="test")
        if "No memory exists for this project yet" in out:
            is_cold_start = True
            mem_ctx_tokens = 80
        else:
            mem_ctx_tokens = len(out) // 4
    except Exception:
        pass

    rules_tokens = 0
    try:
        res = subprocess.run(
            ["node", "-e", "const {BASEMEM_RULES_TIER1} = require('./bin/lib/rules.js'); process.stdout.write(BASEMEM_RULES_TIER1)"],
            capture_output=True, text=True, timeout=5
        )
        out = res.stdout if res.returncode == 0 else ""
        rules_tokens = len(out) // 4
    except Exception:
        pass

    code_stats_tokens = 15
    total_injection = mem_ctx_tokens + rules_tokens + code_stats_tokens

    # 2. MCP Tool Schemas
    total_schema_cost = 0
    top_tools = []
    try:
        from mcp_server.server import server
        tools = asyncio.run(server.list_tools())
        tool_costs = []
        for t in tools:
            s_dump = json.dumps(t.model_dump())
            c = len(s_dump) // 4
            tool_costs.append((t.name, c))
            total_schema_cost += c
        tool_costs.sort(key=lambda x: x[1], reverse=True)
        top_tools = tool_costs[:5]
    except Exception:
        total_schema_cost = 4620

    # 3. Codebase Token Cost
    cwd = Path.cwd().absolute()
    code_db_path = None
    curr = cwd
    while True:
        candidate = curr / ".basemem.code.db"
        if candidate.is_file():
            code_db_path = candidate
            break
        if (curr / ".git").is_dir():
            candidate_git = curr / ".basemem.code.db"
            if candidate_git.is_file():
                code_db_path = candidate_git
            break
        parent = curr.parent
        if parent == curr:
            break
        curr = parent

    codebase_lines = []
    reduction_factor = 100
    if code_db_path:
        project_dir = code_db_path.parent
        project_name = project_dir.name
        n_files = 0
        n_symbols = 0
        try:
            res = subprocess.run(
                ["mem", "code", "status"],
                capture_output=True, text=True, timeout=5, cwd=str(project_dir)
            )
            out = res.stdout.strip()
            import re
            m = re.search(r'(\d+)\s+files?,\s*(\d+)\s+symbols?', out, re.I) or re.search(r'(\d+)f\s+(\d+)s', out, re.I)
            if m:
                n_files = int(m.group(1))
                n_symbols = int(m.group(2))
        except Exception:
            pass

        total_bytes = 0
        if code_db_path.is_file():
            try:
                import sqlite3
                conn = sqlite3.connect(str(code_db_path))
                rows = conn.execute("SELECT DISTINCT file_path FROM code_symbols").fetchall()
                conn.close()
                for (fp,) in rows:
                    abs_fp = project_dir / fp
                    if abs_fp.is_file():
                        total_bytes += abs_fp.stat().st_size
            except Exception:
                pass

        whole_codebase_tokens = max(total_bytes // 4, 30000)
        review_context_tokens = 300
        reduction_factor = max(whole_codebase_tokens // review_context_tokens, 100)

        codebase_lines = [
            f"  Project: {project_name} ({project_dir})",
            f"  Indexed: {n_files} files, {n_symbols} symbols",
            f"  Reading whole codebase:  ~{whole_codebase_tokens:,} tokens",
            f"  Using get_review_context:   ~{review_context_tokens} tokens",
            f"  Reduction factor:            ~{reduction_factor}x",
        ]
    else:
        codebase_lines = [
            "  Code index not initialized — run mem code init"
        ]

    # 4. Per-session estimates
    fixed_cost = total_injection + 5070
    turns = 10
    after_10_turns = fixed_cost * turns
    basemem_contrib = fixed_cost
    history_contrib = after_10_turns - fixed_cost
    basemem_pct = round((basemem_contrib / after_10_turns) * 100) if after_10_turns else 0
    history_pct = 100 - basemem_pct

    lines = [
        "BaseMem Token Budget",
        "────────────────────────────────────────────",
        "Session start injection",
        f"  Memory context:              {'~80 tokens (cold start — no planet yet)' if is_cold_start else f'~{mem_ctx_tokens:,} tokens'}",
        f"  Rules text (TIER1):          ~{rules_tokens:,} tokens",
        f"  Code index stats:             ~{code_stats_tokens} tokens",
        f"  Total injection:             ~{total_injection:,} tokens",
    ]
    if is_cold_start:
        lines.append("  Note: Run 'mem planet create <topic>' to enable full memory context injection.")
    lines.extend([
        "",
        f"MCP Tool Schemas (25 core tools)",
        f"  Total schema cost:         ~{total_schema_cost:,} tokens",
        "  Largest tools:",
    ])
    for name, c in top_tools:
        lines.append(f"    {name:<26} ~{c:,} tokens")

    lines.extend([
        "",
        "Codebase Token Cost",
        *codebase_lines,
        "",
        "Estimated per-session cost",
        f"  Fresh session (turn 1):  ~{fixed_cost:,} tokens",
        f"  After 10 turns:          ~{after_10_turns:,} tokens",
        f"  BaseMem contribution:    ~{basemem_contrib:,} tokens (~{basemem_pct}%)",
        f"  Conversation history:    ~{history_contrib:,} tokens (~{history_pct}%)",
    ])

    click.echo("\n".join(lines))


@cli.command()
@click.option('--topic', help='Recompute only within a specific planet')
@click.option('--threshold', default=0.1, type=float, help='Jaccard threshold for new links')
@click.option('--min-weight', default=0.05, type=float, help='Remove auto-links below this weight')
@click.pass_context
def recompute_links(ctx, topic, threshold, min_weight):
    """Recompute Jaccard similarity for all notes. Updates weights, creates new links, prunes weak ones."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    click.echo("Recomputing note links (this may take a moment)...")
    result = manager.recompute_links(topic=topic, threshold=threshold, min_weight=min_weight)
    click.echo(f"  Created: {result['created']} new links")
    click.echo(f"  Removed: {result['removed']} weak links")
    click.echo(f"  Evaluated: {result['total_pairs']} note pairs")


@cli.command()
def migrate():
    """Run pending database schema migrations."""
    from storage.db import StorageManager
    from storage.sessions import _ensure_schema
    from pathlib import Path
    import os

    db_path = os.environ.get("BASEMEM_DB_PATH") or str(Path.home() / ".basemem" / "basemem.db")
    _ensure_schema(StorageManager(db_path).connection)
    click.echo("Schema up-to-date.")


@cli.command(name="prompt-context")
@click.option('--topic', '-t', default=None, help='Topic/planet name (defaults to cwd project)')
@click.option('--query', '-q', required=True, help='User prompt text to search for relevant context')
@click.option('--root', default='.', help='Project root for code index lookup (defaults to cwd)')
@click.option('--limit', default=3, type=int, help='Max hits per source (memory + code)')
@click.option('--format', 'out_format', type=click.Choice(['text', 'json']), default='text')
@click.option('--max-chars', default=1500, type=int, help='Max output characters (text format)')
@click.pass_context
def prompt_context(ctx, topic, query, root, limit, out_format, max_chars):
    """Query-aware recall: FTS5 search memory notes + code symbols for a user prompt.

    Designed for UserPromptSubmit hooks: fast (<1s), silent on failure,
    prints nothing when no relevant context is found (exit 0).
    """
    import os
    text = (query or '').strip()
    if len(text) < 8:
        return  # too short to be meaningful — stay silent
    # Cap prompt length sent into FTS tokenizers
    if len(text) > 2000:
        text = text[:2000]
    from storage.sessions import SessionManager
    from storage.notes import tokenize_query
    manager = SessionManager(ctx.obj['storage'])
    if not topic:
        topic = _topic_from_cwd() or get_project_root()

    tokens = tokenize_query(text)
    if not tokens:
        return

    exclude_ids = _read_injected_exclude_ids(topic)

    mem_hits: list = []
    try:
        # True FTS5 recall over notes_fts (topic-scoped, falls back to LIKE).
        # Suppress notes already surfaced by the most recent agent-context call.
        mem_hits = manager.search_notes_fts(
            topic, ' '.join(tokens[:12]), limit=limit, exclude_ids=exclude_ids
        ) or []
    except Exception:
        mem_hits = []

    code_hits: list = []
    try:
        from indexer import CODE_DB_FILENAME, CodeIndexer
        croot = os.path.abspath(root or os.getcwd())
        # Walk up to 3 levels to find the code index (hook cwd may be a subdir)
        db_path = None
        cur = croot
        for _ in range(4):
            cand = os.path.join(cur, CODE_DB_FILENAME)
            if os.path.isfile(cand):
                db_path = cand
                croot = cur
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        if db_path:
            indexer = CodeIndexer(croot)
            try:
                code_hits = indexer.search_symbols(' '.join(tokens[:8]), limit=limit) or []
            finally:
                try:
                    indexer.close()
                except Exception:
                    pass
    except Exception:
        code_hits = []

    if not mem_hits and not code_hits:
        return

    if out_format == 'json':
        click.echo(json.dumps({'memory': mem_hits, 'code': code_hits}, default=str))
        return

    lines: list[str] = []
    if mem_hits:
        lines.append('[Relevant memory]')
        for n in mem_hits[:limit]:
            kind = (n.get('kind') or 'note')
            title = (n.get('title') or '')[:100]
            content = ' '.join((n.get('content') or '').split())[:300]
            lines.append(f"- ({kind}) {title}: {content}" if title else f"- ({kind}) {content}")
    if code_hits:
        lines.append('[Relevant code]')
        for s in code_hits[:limit]:
            sig = ' '.join((s.get('signature') or '').split())[:160]
            loc = f"{s.get('file_path')}:{s.get('start_line')}-{s.get('end_line')}"
            desc = f"{s.get('symbol_name')} ({s.get('symbol_type')}) {loc}"
            if sig:
                desc += f" — {sig}"
            lines.append(f"- {desc}"[:350])
    out = '\n'.join(lines)
    if len(out) > max_chars:
        out = out[:max_chars - 3].rstrip() + '...'
    click.echo(out)


@cli.command()
@click.option('--planet', help='Export only a specific planet')
@click.option('--output', '-o', default='basemem-export.json', help='Output file path')
@click.pass_context
def export(ctx, planet, output):
    """Export knowledge base to JSON."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    data = manager.export_kb(planet=planet)
    out_path = Path(output)
    out_path.write_text(json.dumps(data, indent=2, default=str))
    click.echo(f"[ok] Exported to {out_path.resolve()} ({len(data['planets'])} planets, {len(data['notes'])} notes, {len(data['note_links'])} note links)")


@cli.command()
@click.argument('input', required=False, default='basemem-export.json')
@click.pass_context
def import_kb(ctx, input):
    """Import knowledge base from JSON. Skips existing planets/notes."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    in_path = Path(input)
    if not in_path.exists():
        click.echo(f"[!] File not found: {in_path}")
        return
    data = json.loads(in_path.read_text())
    stats = manager.import_kb(data)
    click.echo(f"Import results: {stats['planets_created']} planets created, {stats['planets_skipped']} skipped, "
               f"{stats['notes_created']} notes created, {stats['notes_skipped']} skipped, "
               f"{stats['note_links']} note links, {stats['planet_links']} planet links")
    if stats['errors']:
        click.echo(f"Errors: {len(stats['errors'])}")
        for e in stats['errors'][:5]:
            click.echo(f"  {e}")


@cli.command()
def doctor():
    """Run system diagnostics and integrity checks."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    base_dir = Path(__file__).parent.parent.absolute()
    checks = []
    all_pass = True

    db_path = os.environ.get("BASEMEM_DB_PATH") or str(Path.home() / ".basemem" / "basemem.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        expected = {'planets', 'notes', 'note_links', 'planet_links', 'sessions', 'tasks'}
        missing = expected - tables
        if missing:
            checks.append(('Database schema', f'fail: missing tables {missing}'))
            all_pass = False
        else:
            checks.append(('Database schema', 'pass'))
    except Exception as e:
        checks.append(('Database access', f'fail: {e}'))
        all_pass = False

    try:
        import mcp_server.server
        checks.append(('MCP server import', 'pass'))
    except Exception as e:
        checks.append(('MCP server import', f'fail: {e}'))
        all_pass = False

    try:
        subprocess.run(['which', 'mem'], capture_output=True, check=True)
        checks.append(('mem CLI on PATH', 'pass'))
    except Exception:
        checks.append(('mem CLI on PATH', 'fail'))
        all_pass = False

    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip().lstrip('v')
        major = int(version.split('.')[0])
        if major >= 18:
            checks.append(('Node.js version', f'pass ({version})'))
        else:
            checks.append(('Node.js version', f'fail: {version} < 18'))
            all_pass = False
    except Exception as e:
        checks.append(('Node.js', f'fail: {e}'))
        all_pass = False

    try:
        repair_result = subprocess.run(
            ['node', str(base_dir / 'bin' / 'lib' / 'install.js'), 'repair', '--dry-run'],
            capture_output=True, text=True, timeout=30
        )
        checks.append(('Agent integrity check', 'pass (dry-run completed)'))
        for line in repair_result.stdout.split('\n'):
            line = line.strip()
            if line and 'repaired' in line:
                all_pass = False
    except Exception as e:
        checks.append(('Agent integrity check', f'fail: {e}'))
        all_pass = False

    click.echo('\nBaseMem Doctor:')
    click.echo('─' * 60)
    for name, result in checks:
        status = '✓' if result.startswith('pass') else '✗'
        click.echo(f'  {status} {name}: {result}')
    click.echo('─' * 60)
    if all_pass:
        click.echo('All checks passed.')
        sys.exit(0)
    else:
        click.echo('Some checks failed.')
        sys.exit(1)


@cli.command()
@click.argument('doc_name', required=False)
@click.pass_context
def docs(ctx, doc_name):
    """Read project documentation files (readme, implementation, etc.)."""
    base = Path(__file__).parent.parent.absolute()
    m = {}
    for p in sorted(base.glob("*.md")) + sorted(base.glob("doc/*.md")):
        name = p.stem.lower().replace("_", "-").replace(" ", "-")
        m[name] = p
    if not doc_name:
        click.echo("Available: " + ", ".join(m.keys()))
        return
    path = m.get(doc_name.lower())
    if not path or not path.exists():
        click.echo(f"Not found: {doc_name}")
        return
    click.echo(path.read_text())


if __name__ == '__main__':
    cli(prog_name='mem')
