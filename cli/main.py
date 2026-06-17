"""Main CLI interface using Click (Full Search Version)"""

import click
from pathlib import Path
import logging
import os
import sys

from storage.db import StorageManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def get_project_root():
    """Find the nearest project root (folder with AGENTS.md, .git, or fallback to current)"""
    curr = Path.cwd().absolute()
    for parent in [curr] + list(curr.parents):
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent.name
    return curr.name

@click.group(name='mem')
@click.option('--db', help='Database path')
@click.pass_context
def cli(ctx, db):
    """BaseMem: AI Knowledge Base Ledger"""
    ctx.ensure_object(dict)
    ctx.obj['db'] = db or str(Path.home() / ".basemem" / "basemem.db")
    ctx.obj['storage'] = StorageManager(ctx.obj['db'])

@cli.command("list-planets")
@click.pass_context
def list_planets(ctx):
    """List all planets in the knowledge base."""
    import sqlite3, json
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
    import sqlite3
    conn = sqlite3.connect(ctx.obj['db'])
    conn.row_factory = sqlite3.Row
    click.echo(f"Searching for: '{query}'...")

    like = f"%{query}%"
    results = []

    # Planets
    for r in conn.execute(
        "SELECT topic, display_topic, current_state, goal, updated_at FROM planets WHERE topic LIKE ? OR display_topic LIKE ? OR current_state LIKE ? OR goal LIKE ?",
        (like, like, like, like),
    ):
        name = r["display_topic"] or r["topic"]
        preview = (r["current_state"] or r["goal"] or "")[:150].replace("\n", " ").strip()
        results.append(("planet", name, f"planet-{r['topic']}", preview))

    # Notes (select id explicitly to avoid KeyError)
    for r in conn.execute(
        "SELECT id, topic, kind, content, created_at FROM notes WHERE content LIKE ? OR title LIKE ?",
        (like, like),
    ):
        preview = r["content"][:150].replace("\n", " ").strip()
        label = f"{r['topic']} / {r['kind']}"
        results.append(("note", label, f"note-{r['id']}", preview))
    conn.close()

    # Old nodes (FTS fallback)
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
    for kind, title, rid, preview in results:
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
        active = manager.get_active_planet()
        if active:
            resolved_topic = active.metadata.get("display_topic") or active.metadata.get("topic") or active.title
        else:
            resolved_topic = root_name

    click.echo(manager.build_agent_context(resolved_topic, query=query))

@cli.command()
@click.pass_context
def stats(ctx):
    storage = ctx.obj['storage']
    click.echo(f"\n[*] Galaxy Nodes: {len(storage.get_all_nodes())}")
    click.echo(f"[*] Galaxy Bridges: {len(storage.get_edges())}")

@cli.group()
def session():
    pass

@session.command()
@click.pass_context
def last_topic(ctx):
    storage = ctx.obj['storage']
    from storage.sessions import SessionManager
    manager = SessionManager(storage)
    planet = manager.get_active_planet()
    if planet:
        click.echo(planet.title)

@session.command()
@click.pass_context
def active(ctx):
    """Return the name of the most recently updated planet."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.get_active_planet()
    if node:
        click.echo(node.title)

@session.command()
@click.pass_context
def context(ctx):
    """Tier 1 Discovery: High-Fidelity Knowledge Briefing"""
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])

    sun_node = manager.get_or_create_folder_hub(root_name)
    click.echo(f"\n[SUN] ROOT HUB: {sun_node.title}")

    cursor = ctx.obj['storage'].connection.cursor()
    rows = cursor.execute(
        "SELECT topic, display_topic, status, goal, current_state, next_steps, updated_at FROM planets ORDER BY updated_at DESC"
    ).fetchall()
    click.echo(f"\n[PLANETS] ACTIVE PLANETS (TASKS):")
    if rows:
        for row in rows:
            topic = row["display_topic"] or row["topic"]
            click.echo(f"\n--- Planet: {topic} (ID: planet-{row['topic']}) ---")
            click.echo(f"  Status: {row['status'] or 'active'}")
            preview = (row['goal'] or row['current_state'] or "")[:300].replace("\n", " ").strip()
            if preview:
                click.echo(f"  Context: {preview}...")
            next_steps = json.loads(row['next_steps'] or "[]")
            if next_steps:
                click.echo(f"  Next: {next_steps[-1]}")
    else:
        click.echo("  No active tasks.")

@session.command()
@click.option('--message', '-m', required=True)
@click.option('--topic', '-t', required=True)
@click.option('--agent-id', default='default')
@click.pass_context
def turn(ctx, message, topic, agent_id):
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    manager.log_chat_to_planet(root_name, topic, message, agent_id)
    click.echo(f"[ok] Turn logged to Planet: {topic}")

@session.command()
@click.option('--agent-id', required=True)
@click.option('--topic', '-t', required=True)
@click.option('--file', 'chat_file', type=click.Path(exists=True), help='Transcript file to archive')
@click.pass_context
def sync(ctx, agent_id, topic, chat_file):
    root_name = get_project_root()
    import json, glob
    if not chat_file:
        home = str(Path.home())
        patterns = [
            f"{home}/.gemini/tmp/*/chats/session-*-{agent_id}.json",
            f"{home}/.codex/sessions/**/rollout-*-{agent_id}.jsonl",
            f"{home}/.claude/**/*.json*",
            f"/tmp/ai-chats/**/*{agent_id}*.json*",
            f"/tmp/**/*{agent_id}*.json*",
        ]
        files = []
        for pattern in patterns:
            files.extend(glob.glob(pattern, recursive=True))
        if not files: return
        chat_file = max(files, key=lambda p: Path(p).stat().st_mtime)
    try:
        transcript = f"Full Archive of {topic}\n"
        if chat_file.endswith(".jsonl"):
            with open(chat_file, "r") as f:
                for line in f:
                    event = json.loads(line)
                    payload = event.get("payload", {})
                    msg = payload if payload.get("type") == "message" else event
                    sender = (msg.get("role") or msg.get("sender") or msg.get("type") or "unknown").upper()
                    if sender not in {"USER", "ASSISTANT"}:
                        continue
                    parts = []
                    content_value = msg.get("content") or msg.get("text") or msg.get("message") or ""
                    if isinstance(content_value, list):
                        for part in content_value:
                            if isinstance(part, dict):
                                text = part.get("text") or part.get("input_text") or part.get("output_text")
                                if text:
                                    parts.append(text)
                    elif isinstance(content_value, str):
                        parts.append(content_value)
                    elif content_value:
                        parts.append(json.dumps(content_value))
                    content = "\n".join(parts).strip()
                    if content:
                        transcript += f"\n\n--- [{event.get('timestamp', 'unknown')}] {sender} ---\n{content}"
        else:
            with open(chat_file, "r") as f: data = json.load(f)
            if isinstance(data, dict):
                msgs = data.get("messages") or data.get("conversation") or data.get("items") or [data]
            else:
                msgs = data
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                sender = (msg.get("type") or msg.get("role") or msg.get("sender") or "unknown").upper()
                content = msg.get("content") or msg.get("text") or msg.get("message") or ""
                if isinstance(content, list):
                    content = "\n".join([p.get("text") or p.get("input_text") or p.get("output_text") or "" for p in content if isinstance(p, dict)])
                if isinstance(content, dict):
                    content = json.dumps(content)
                if content:
                    transcript += f"\n\n--- [{msg.get('timestamp') or msg.get('created_at') or 'unknown'}] {sender} ---\n{content}"
        from storage.sessions import SessionManager
        manager = SessionManager(ctx.obj['storage'])
        node = manager.ingest_archive_moon(root_name, topic, transcript, agent_id)
        if node: click.echo(f"[ok] History Archived.")
        else: click.echo(f"[!] Archive ignored: No active planet for '{topic}'.")
    except Exception as e: click.echo(f"Sync failed: {e}")

@session.command()
@click.argument('node_id', required=False)
@click.option('--topic', '-t', help='Read a planet by topic instead of node id')
@click.pass_context
def read(ctx, node_id, topic):
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.get_planet(topic) if topic else ctx.obj['storage'].get_node(node_id)
    if node: click.echo(f"\n{node.title}:\n\n{node.content}")
    else: click.echo("Node not found.")

@cli.group()
def planet():
    """Manage shared task planets."""
    pass

@planet.command("create")
@click.argument('topic')
@click.option('--goal')
@click.option('--status', default='active')
@click.option('--state', 'current_state')
@click.pass_context
def planet_create(ctx, topic, goal, status, current_state):
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.get_or_create_task_planet(root_name, topic)
    node = manager.update_planet(root_name, topic, status=status, goal=goal, current_state=current_state)
    click.echo(f"[ok] Planet ready: {node.title} ({node.id})")

@planet.command("read")
@click.argument('topic')
@click.pass_context
def planet_read(ctx, topic):
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.get_planet(topic)
    if not node:
        click.echo("Planet not found.")
        return
    click.echo(f"\n{node.title}:\n\n{node.content}")

@planet.command("set")
@click.argument('topic')
@click.option('--status')
@click.option('--goal')
@click.option('--state', 'current_state')
@click.option('--next', 'next_step')
@click.option('--file', 'file_path')
@click.option('--command')
@click.option('--handoff')
@click.pass_context
def planet_set(ctx, topic, status, goal, current_state, next_step, file_path, command, handoff):
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.update_planet(
        root_name,
        topic,
        status=status,
        goal=goal,
        current_state=current_state,
        next_step=next_step,
        file_path=file_path,
        command=command,
        handoff=handoff,
    )
    click.echo(f"[ok] Planet updated: {node.title}")

@planet.command("compact")
@click.argument('topic')
@click.option('--agent-id', default='default')
@click.option('--summarize/--no-summarize', default=True, help='Generate a summary note before trimming')
@click.pass_context
def planet_compact(ctx, topic, agent_id, summarize):
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    count_before = manager.get_note_count(topic)
    if summarize and count_before > manager.SUMMARIZE_THRESHOLD:
        summary_text = manager.summarize_planet(topic)
        click.echo(summary_text)
        click.echo("")
        if click.confirm("Write a summary for this planet before trimming?"):
            summary = click.prompt("Summary content", default="")
            if summary.strip():
                manager.add_note(root_name, topic, "summary", summary, agent_id=agent_id)
                click.echo("[ok] Summary note added.")
    node = manager.compact_planet(root_name, topic, agent_id=agent_id)
    click.echo(f"[ok] Planet compacted: {node.title} ({count_before} -> {manager.get_note_count(topic)} notes)")

@planet.command("summarize")
@click.argument('topic')
@click.option('--limit', default=50, help='Max notes to include (default 50). Excludes existing summaries.')
@click.pass_context
def planet_summarize(ctx, topic, limit):
    """Print notes formatted for an agent to write a summary. Skips old summaries, truncates long notes."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    click.echo(manager.summarize_planet(topic, limit=limit))

@planet.command("delete")
@click.argument('topic')
@click.pass_context
def planet_delete(ctx, topic):
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    if not manager.get_planet(topic):
        click.echo("Planet not found.")
        return
    if click.confirm(f"Are you sure you want to delete planet '{topic}'?"):
        manager.delete_planet(topic)
        click.echo(f"[ok] Planet deleted: {topic}")

@planet.command("link")
@click.argument('from_topic')
@click.argument('to_topic')
@click.option('--relation', default='related', help='Relation type: related, depends, implements')
@click.option('--weight', default=1.0, type=float)
@click.pass_context
def planet_link(ctx, from_topic, to_topic, relation, weight):
    """Link two planets together."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.link_planets(from_topic, to_topic, relation, weight)
    if ok:
        click.echo(f"[ok] {msg}")
    else:
        click.echo(f"[!] {msg}")

@planet.command("linked")
@click.argument('topic')
@click.pass_context
def planet_linked(ctx, topic):
    """Show planets linked to the given planet."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    links = manager.get_planet_links(topic)
    if not links:
        click.echo("No planet links found.")
        return
    click.echo(f"Planets linked to '{topic}':\n")
    for l in links:
        click.echo(f"  {l['planet']} [{l['relation']}] (w={l['weight']})")

@planet.command("set-state")
@click.argument('topic')
@click.argument('state', type=click.Choice(['hot', 'warm', 'compacted']))
@click.pass_context
def planet_set_state(ctx, topic, state):
    """Set memory state: hot, warm, or compacted."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.set_memory_state(topic, state)
    if ok:
        click.echo(f"[ok] {msg}")
    else:
        click.echo(f"[!] {msg}")

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

@cli.group()
def note():
    """Manage notes on a planet. Use `kb note add` to create notes, `kb note link` to connect them."""
    pass


@note.command("add")
@click.argument('topic')
@click.option('--type', 'kind', default='fact', help='decision, fact, task, issue, question, concept, example')
@click.option('--message', '-m', required=True)
@click.option('--title')
@click.option('--status', default='open')
@click.option('--agent-id', default='default')
@click.pass_context
def note_add(ctx, topic, kind, message, title, status, agent_id):
    """Add a typed collaboration note linked to a planet."""
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.add_note(root_name, topic, kind, message, agent_id=agent_id, title=title, status=status)
    msg = f"[ok] Note added: {node['title']} ({node['id']})"
    if node.get("_suggest"):
        msg += f"\n  [!] {node['_suggest']}"
    click.echo(msg)


@note.command("link")
@click.argument('from_id')
@click.argument('to_id')
@click.option('--type', 'link_type', default='related', help='Link type: related, depends, implements')
@click.pass_context
def note_link(ctx, from_id, to_id, link_type):
    """Create a link between two notes. IDs are the note-<number> format."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.link_notes(from_id, to_id, link_type)
    if ok:
        click.echo(f"[ok] {msg}")
    else:
        click.echo(f"[!] {msg}")


@note.command("neighbors")
@click.argument('note_id')
@click.option('--link-type', help='Filter by link type')
@click.pass_context
def note_neighbors(ctx, note_id, link_type):
    """Show notes connected to the given note via links."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    neighbors = manager.get_note_neighbors(note_id, link_type=link_type)
    if not neighbors:
        click.echo("No linked notes found.")
        return
    click.echo(f"Neighbors of {note_id} ({len(neighbors)}):\n")
    for n in neighbors:
        name = n["title"] or n["content"][:80]
        click.echo(f"  note-{n['id']} [{n['link_type']}] (w={n['weight']}) {name}")

# ── Edge commands ─────────────────────────────────────────

@cli.group()
def edge():
    """Manage edge lifecycle: decay and prune."""
    pass


@edge.command("decay")
@click.option('--factor', default=0.9, type=float, help='Multiply all auto-link weights by this factor')
@click.option('--planet', help='Limit to a specific planet')
@click.pass_context
def edge_decay(ctx, factor, planet):
    """Apply weight decay to auto-links. Reduces old/unused connections."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    result = manager.edge_decay(factor=factor, planet=planet)
    click.echo(f"Decayed {result['decayed']} edge(s) by factor {result['factor']}.")


@edge.command("prune")
@click.option('--threshold', default=0.05, type=float, help='Remove auto-links below this weight')
@click.option('--planet', help='Limit to a specific planet')
@click.pass_context
def edge_prune(ctx, threshold, planet):
    """Remove auto-links below a weight threshold."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    result = manager.edge_prune(threshold=threshold, planet=planet)
    click.echo(f"Pruned {result['pruned']} edge(s) below threshold {result['threshold']}.")


# ── Export / Import ─────────────────────────────────────

@cli.command()
@click.option('--planet', help='Export only a specific planet')
@click.option('--output', '-o', default='basemem-export.json', help='Output file path')
@click.pass_context
def export(ctx, planet, output):
    """Export knowledge base to JSON."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    data = manager.export_kb(planet=planet)
    import json
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
    import json
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


# ── Code Graph commands ─────────────────────────────────────

@cli.group()
def code():
    """Code intelligence: index and query source code symbols."""
    pass


@code.command("init")
@click.argument('project_root', required=False, default='.')
@click.option('--workers', default=4, help='Number of parallel workers')
@click.pass_context
def code_init(ctx, project_root, workers):
    """Index a project's source code into the knowledge graph."""
    import os
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        with click.progressbar(length=1, label='Indexing...') as bar:
            result = indexer.index_project(root, max_workers=workers)
            bar.update(1)
        click.echo(f"[ok] Indexed {result['files']} files, {result['symbols']} symbols, {result['edges']} edges in {result['elapsed']:.1f}s")
    finally:
        indexer.close()


@code.command("list")
@click.option('--limit', default=100, type=int, help='Max symbols')
@click.option('--offset', default=0, type=int, help='Pagination offset')
@click.pass_context
def code_list(ctx, limit, offset):
    """List all indexed code symbols."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code project indexed yet. Run `kb code init`.")
            return
        results = indexer.list_symbols(limit=limit, offset=offset)
        if not results:
            click.echo("No symbols found.")
            return
        total = stats.get('symbol_count', 0)
        click.echo(f"Symbols {offset+1}-{offset+len(results)} of {total}:\n")
        for r in results:
            loc = f"{r['file_path']}:{r['start_line']}-{r['end_line']}"
            click.echo(f"  [{r['id']}] {r['symbol_type']} {r['symbol_name']}  ({loc})")
    finally:
        indexer.close()


@code.command("search")
@click.argument('query')
@click.option('--limit', default=20, type=int)
@click.pass_context
def code_search(ctx, query, limit):
    """Search code symbols by name or signature."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        results = indexer.search_symbols(query, limit=limit)
        if not results:
            click.echo("No matching symbols found. Run `kb code init` first.")
            return
        click.echo(f"Found {len(results)} symbol(s):\n")
        for r in results:
            loc = f"{r['file_path']}:{r['start_line']}-{r['end_line']}"
            sig = f" {r['signature']}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_type']} {r['symbol_name']}{sig}")
            click.echo(f"         {loc}")
            if r.get('docstring'):
                click.echo(f"         doc: {r['docstring'][:150]}")
    finally:
        indexer.close()


@code.command("node")
@click.argument('identifier')
@click.pass_context
def code_node(ctx, identifier):
    """Show details of a code symbol by ID or name."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        sym = None
        try:
            sid = int(identifier)
            sym = indexer.get_symbol(sid)
        except ValueError:
            pass
        if not sym:
            symbols = indexer.get_symbol_by_name(identifier)
            if not symbols:
                click.echo(f"Symbol not found: {identifier}")
                return
            if len(symbols) == 1:
                sym = symbols[0]
            else:
                click.echo(f"Multiple symbols named '{identifier}':")
                for s in symbols:
                    click.echo(f"  [{s['id']}] {s['symbol_type']} in {s['file_path']}:{s['start_line']}")
                return

        callers = indexer.get_callers(sym['symbol_name'])
        callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])

        click.echo(f"{sym['symbol_type']}: {sym['symbol_name']}")
        click.echo(f"  File: {sym['file_path']}:{sym['start_line']}-{sym['end_line']}")
        click.echo(f"  Language: {sym['language']}")
        if sym.get('signature'):
            click.echo(f"  Signature: {sym['signature']}")
        if sym.get('docstring'):
            click.echo(f"  Doc: {sym['docstring']}")
        if callers:
            click.echo(f"  Callers ({len(callers)}):")
            for c in callers[:10]:
                click.echo(f"    {c['symbol_type']} {c['symbol_name']} ({c['edge_file']}:{c['line_number']})")
        if callees:
            click.echo(f"  Calls ({len(callees)}):")
            for c in callees[:10]:
                click.echo(f"    {c['from_name']} (line {c['line_number']})")
    finally:
        indexer.close()


@code.command("callers")
@click.argument('symbol_name')
@click.pass_context
def code_callers(ctx, symbol_name):
    """Find what calls a given symbol."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        results = indexer.get_callers(symbol_name)
        if not results:
            click.echo(f"No callers found for '{symbol_name}'.")
            return
        click.echo(f"Callers of {symbol_name} ({len(results)}):")
        for r in results:
            click.echo(f"  {r['symbol_type']} {r['symbol_name']} in {r['edge_file']}:{r['line_number']}")
    finally:
        indexer.close()


@code.command("callees")
@click.argument('symbol_name')
@click.option('--file-path', help='Limit to a specific file')
@click.pass_context
def code_callees(ctx, symbol_name, file_path):
    """Find what a given symbol calls."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        results = indexer.get_callees(symbol_name, file_path or "")
        if not results:
            click.echo(f"No callees found for '{symbol_name}'.")
            return
        click.echo(f"Callees of {symbol_name} ({len(results)}):")
        for r in results:
            click.echo(f"  {r['from_name']} at {r['file_path']}:{r['line_number']}")
    finally:
        indexer.close()


@code.command("status")
@click.pass_context
def code_status(ctx):
    """Show code graph indexing stats."""
    from indexer import CodeIndexer
    indexer = CodeIndexer(ctx.obj['db'])
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code project indexed yet. Run `kb code init <project_root>`.")
            return
        click.echo(f"Project: {stats.get('name', '?')}")
        click.echo(f"  Root: {stats.get('root_path', '?')}")
        click.echo(f"  Files: {stats['file_count']}")
        click.echo(f"  Symbols: {stats['symbol_count']}")
        click.echo(f"  Edges: {stats.get('edges', 0)}")
        click.echo(f"  Last indexed: {stats.get('last_indexed', 'never')}")
    finally:
        indexer.close()


# ── End Code Graph commands ─────────────────────────────────

@cli.command()
@click.argument('doc_name', required=False)
@click.pass_context
def docs(ctx, doc_name):
    base = Path(__file__).parent.parent.parent.parent.absolute()
    m = {"readme": "README.md", "implementation": "IMPLEMENTATION.md", "development": "DEVELOPMENT.md", "agents": "AGENTS.md"}
    if not doc_name: click.echo("Available: " + ", ".join(m.keys())); return
    path = base / m.get(doc_name.lower(), "")
    if path.exists(): click.echo(path.read_text())

if __name__ == '__main__':
    from basemem.cli import cli
    cli(prog_name='mem')
