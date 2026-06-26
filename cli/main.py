"""Main CLI interface using Click (Full Search Version)"""

import click
from pathlib import Path
import logging
import os

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
    """Show database statistics: node and edge counts."""
    storage = ctx.obj['storage']
    from storage.sessions import SessionManager
    mgr = SessionManager(storage)
    planets = mgr.list_planets()
    note_count = sum(mgr.get_note_count(p["topic"]) for p in planets)
    click.echo(f"\n[*] Planets: {len(planets)}")
    click.echo(f"[*] Notes: {note_count}")
    click.echo(f"[*] Galaxy Nodes: {len(storage.get_all_nodes())}")
    click.echo(f"[*] Galaxy Bridges: {len(storage.get_edges())}")

@cli.group()
def session():
    """Manage session state: active planet, last topic, etc."""

@session.command()
@click.pass_context
def last_topic(ctx):
    """Show the most recently active planet/topic."""
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
    """Log a conversation turn to a planet."""
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
    """Archive a transcript file to a planet."""
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
    """Read a planet or node details."""
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
    """Create a new planet/topic."""
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
    """Read a planet's full details."""
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
    """Update planet fields: status, goal, state, next, files, commands."""
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
    """Trim old notes, keep summaries + 30 recent."""
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
    """Delete a planet and all its notes."""
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
@click.option('--relation', default='related', help='Relation type: related, depends, implements, fixes, duplicates, supersedes, causes, blocks, tests, references')
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
@click.option('--type', 'link_type', default='related', help='Link type: related, depends, implements, fixes, duplicates, supersedes, causes, blocks, tests, references')
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

@note.command("pin")
@click.argument('note_id')
@click.pass_context
def note_pin(ctx, note_id):
    """Pin a note so compact_planet never drops it."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.pin_note(note_id)
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


@note.command("unpin")
@click.argument('note_id')
@click.pass_context
def note_unpin(ctx, note_id):
    """Unpin a previously pinned note."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.unpin_note(note_id)
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


@note.command("tag")
@click.argument('note_id')
@click.argument('tags')
@click.pass_context
def note_tag(ctx, note_id, tags):
    """Tag a note with comma-separated keywords (replaces existing tags)."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ok, msg = manager.tag_note(note_id, tag_list)
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


# ── Task commands ─────────────────────────────────────────

@cli.group()
def task():
    """Manage tasks with dependency tracking and workflow state."""


@task.command("create")
@click.argument('topic')
@click.argument('title')
@click.option('--priority', default='medium', help='low, medium, high')
@click.option('--depends-on', default='', help='Comma-separated task IDs this task depends on')
@click.option('--files', default='', help='Comma-separated file paths')
@click.option('--notes', default='', help='Comma-separated note IDs')
@click.pass_context
def task_create(ctx, topic, title, priority, depends_on, files, notes):
    """Create a new task on a planet."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    deps = [int(d.strip()) for d in depends_on.split(",") if d.strip()] if depends_on else None
    file_list = [f.strip() for f in files.split(",") if f.strip()] if files else None
    note_list = [int(n.strip()) for n in notes.split(",") if n.strip()] if notes else None
    result = manager.create_task(topic, title, priority=priority, depends_on=deps, files=file_list, notes=note_list)
    click.echo(f"[ok] Task created: task-{result['id']} [{result['status']}/{result['priority']}] {result['title']}")


@task.command("set")
@click.argument('task_id', type=int)
@click.option('--status', help='todo, in_progress, blocked, done')
@click.option('--priority', help='low, medium, high')
@click.pass_context
def task_set(ctx, task_id, status, priority):
    """Update a task's status or priority."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.update_task(task_id, status=status, priority=priority)
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


@task.command("block")
@click.argument('task_id', type=int)
@click.option('--reason', help='Optional reason — stored as a linked note with kind=issue')
@click.pass_context
def task_block(ctx, task_id, reason):
    """Mark a task as blocked. If --reason is given, store it as a note and link it."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    if reason:
        row = manager.storage.connection.cursor().execute(
            "SELECT topic, title FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            click.echo(f"[!] Task not found: {task_id}")
            return
        topic_slug = row["topic"]
        note = manager.add_note("", topic_slug, "issue", reason, title=f"Blocked: {row['title']}", status="open")
        nid = int(note["id"].replace("note-", ""))
        existing = json.loads(row["notes"]) if row["notes"] else []
        if nid not in existing:
            existing.append(nid)
            manager.update_task(task_id, notes=existing)
    ok, msg = manager.update_task(task_id, status="blocked")
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


@task.command("done")
@click.argument('task_id', type=int)
@click.pass_context
def task_done(ctx, task_id):
    """Mark a task as done."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok, msg = manager.update_task(task_id, status="done")
    click.echo(f"[ok] {msg}" if ok else f"[!] {msg}")


@task.command("list")
@click.option('--topic', help='Filter by planet topic')
@click.option('--status', help='Filter by status: todo, in_progress, blocked, done')
@click.option('--priority', help='Filter by priority: low, medium, high')
@click.pass_context
def task_list(ctx, topic, status, priority):
    """List tasks, optionally filtered by topic, status, or priority."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    tasks = manager.list_tasks(topic=topic, status=status, priority=priority)
    if not tasks:
        click.echo("No tasks found.")
        return
    click.echo(f"Tasks ({len(tasks)}):\n")
    for t in tasks:
        deps = json.loads(t.get("depends_on", "[]"))
        dep_str = f" depends_on: {deps}" if deps else ""
        click.echo(f"  task-{t['id']} [{t['status']}/{t['priority']}] {t['title']}{dep_str}")


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


def _get_code_indexer(project_root: str):
    """Create a CodeIndexer from a project root directory."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return None
    db_path = os.path.join(root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index found at {db_path}. Run `kb code init {root}` first.")
        return None
    return CodeIndexer(root)


@code.command("init")
@click.argument('project_root', required=False, default='.')
@click.option('--workers', default=4, help='Number of parallel workers')
@click.option('--watch', is_flag=True, help='Watch for file changes and auto-reindex')
def code_init(project_root, workers, watch):
    """Index a project into a per-project .basemem.code.db."""
    import os
    import signal
    from indexer import CodeIndexer
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return
    indexer = CodeIndexer(root)
    try:
        with click.progressbar(length=1, label='Indexing...') as bar:
            result = indexer.index_project(max_workers=workers)
            bar.update(1)
        click.echo(f"[ok] Indexed {result['files']} files, {result['symbols']} symbols, {result['edges']} edges in {result['elapsed']:.1f}s")
        click.echo(f"     DB: {indexer.db_path}")

        if watch:
            from indexer.watcher import CodeGraphWatcher
            watcher = CodeGraphWatcher(root, indexer)
            watcher.start()
            click.echo(f" Watching {root} for changes (Ctrl+C to stop)...")
            signal.signal(signal.SIGINT, lambda s, f: (watcher.stop(), exit(0)))
            signal.pause()
    finally:
        if not watch:
            indexer.close()


def _fmt_loc(file_path: str, line: int = 0) -> str:
    path = file_path.replace("\\", "/")
    for prefix in ("src/basemem/", "basemem/"):
        if path.startswith(prefix):
            path = path.removeprefix(prefix)
            break
    parts = path.split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else path


@code.command("list")
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=100, type=int, help='Max symbols')
@click.option('--offset', default=0, type=int, help='Pagination offset')
def code_list(root, limit, offset):
    """List all indexed code symbols in a project."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code indexed.")
            return
        results = indexer.list_symbols(limit=limit, offset=offset)
        if not results:
            click.echo("No symbols found.")
            return
        total = stats.get('symbol_count', 0)
        click.echo(f"sym {offset+1}-{offset+len(results)}/{total}")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}) {r['symbol_type'][:4]}")
    finally:
        indexer.close()


@code.command("search")
@click.argument('query')
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=20, type=int)
@click.option('--regex', is_flag=True, help='Interpret query as Python regex pattern')
def code_search(query, root, limit, regex):
    """Search code symbols by name or signature."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.search_symbols(query, limit=limit, use_regex=regex)
        if not results:
            click.echo(f"No match for '{query}'.")
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("node")
@click.argument('identifier')
@click.option('--root', default='.', help='Project root directory')
def code_node(identifier, root):
    """Show details of a code symbol by ID or name."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
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
                click.echo(f"Not found: {identifier}")
                return
            if len(symbols) == 1:
                sym = symbols[0]
            else:
                click.echo(f"Multiple '{identifier}':")
                for s in symbols:
                    loc = _fmt_loc(s['file_path'], s['start_line'])
                    click.echo(f"  [{s['id']}] ({loc})")
                return

        callers = indexer.get_callers(sym['symbol_name'])
        callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
        loc = _fmt_loc(sym['file_path'], sym['start_line'])

        click.echo(f"{sym['symbol_name']} ({loc}) {sym['language']}")
        if sym.get('signature'):
            click.echo(f"  sig: {sym['signature']}")
        if sym.get('docstring'):
            click.echo(f"  doc: {sym['docstring'][:200]}")
        if callers:
            callers_str = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10])
        click.echo(f"  callers: {callers_str}")
        if callees:
            callees_str = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
            click.echo(f"  calls: {callees_str}")
    finally:
        indexer.close()


@code.command("callers")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
def code_callers(symbol_name, root):
    """Find what calls a given symbol."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_callers(symbol_name)
        if not results:
            click.echo(f"No callers for '{symbol_name}'.")
            return
        results_str = ", ".join(f"{r['symbol_name']}:{r['line_number']}" for r in results[:20])
        click.echo(f"callers of {symbol_name}: {results_str}")
    finally:
        indexer.close()


@code.command("callees")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--file-path', help='Limit to a specific file')
def code_callees(symbol_name, root, file_path):
    """Find what a given symbol calls."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_callees(symbol_name, file_path or "")
        if not results:
            click.echo(f"No callees for '{symbol_name}'.")
            return
        results_str = ", ".join(f"{r['to_name']}:{r['line_number']}" for r in results[:20])
        click.echo(f"callees of {symbol_name}: {results_str}")
    finally:
        indexer.close()


@code.command("trace")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--direction', default='both', type=click.Choice(['inbound', 'outbound', 'both']))
def code_trace(symbol_name, root, direction):
    """Trace call chain: inbound (callers), outbound (callees), or both."""
    from indexer import CodeIndexer, CODE_DB_FILENAME
    import os
    db_path = os.path.join(os.path.abspath(root), CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"No code index at {db_path}. Run `kb code init {root}` first.")
        return
    indexer = CodeIndexer(root)
    try:
        out = []
        if direction in ('inbound', 'both'):
            callers = indexer.get_callers(symbol_name)
            if callers:
                out.append(f"<- {', '.join(c['symbol_name'] for c in callers[:8])}")
        if direction in ('outbound', 'both'):
            callees = indexer.get_callees(symbol_name)
            if callees:
                out.append(f"-> {', '.join(c['to_name'] for c in callees[:8])}")
        if not out:
            click.echo(f"{symbol_name}: no call chain")
            return
        click.echo(f"{symbol_name}: {'; '.join(out)}")
    finally:
        indexer.close()


@code.command("sync")
@click.argument('path', required=False, default='.')
@click.option('--workers', default=4, help='Number of parallel workers')
def code_sync(path, workers):
    """Incremental re-index: only re-index files changed since last index."""
    import os
    from indexer import CodeIndexer
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return
    indexer = CodeIndexer(root)
    try:
        result = indexer.sync_index(max_workers=workers)
        if result.get("status") == "unchanged":
            click.echo("No changes detected.")
            return
        click.echo(f"[ok] Synced: {result.get('files_changed', 0)} files changed, "
                   f"{result['symbols_added']} symbols, {result['edges_added']} edges, "
                   f"{result.get('files_removed', 0)} removed")
    finally:
        indexer.close()


@code.command("find")
@click.argument('query', required=False, default='')
@click.option('--root', default='.', help='Project root directory')
@click.option('--dead', is_flag=True, help='Find files never imported by other files (import-chain analysis)')
@click.option('--verbose', is_flag=True, help='Show symbols within dead files')
@click.option('--file-path', help='Filter to a specific file')
@click.option('--limit', default=20, type=int, help='Max results')
@click.option('--regex', is_flag=True, help='Interpret query as regex')
def code_find_cli(query, root, dead, verbose, file_path, limit, regex):
    """Find code symbols by name, detail, dead, or file. Mirrors MCP code_find."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    root_path = os.path.abspath(root)
    db_path = os.path.join(root_path, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index at {db_path}. Run `mem code init` first.")
        return
    indexer = CodeIndexer(root_path)
    try:
        if dead:
            results = indexer.find_dead_exports(limit=0)
            if not results:
                click.echo("All files are reachable via imports.")
                return
            click.echo(f"{len(results)} file(s) never imported by other files:")
            if verbose:
                for r in results:
                    click.echo(f"\n  {r['file_path']} ({r['symbol_count']} symbols):")
                    symbols = indexer.list_symbols_by_file(r['file_path'], limit=0)
                    for s in symbols[:10]:
                        sig = f" {s['signature'][:60]}" if s.get('signature') else ""
                        click.echo(f"    [{s['symbol_type'][:4]}] {s['symbol_name']}{sig}")
                    if len(symbols) > 10:
                        click.echo(f"    ... and {len(symbols) - 10} more")
            else:
                for r in results:
                    click.echo(f"  {r['file_path']} ({r['symbol_count']} symbols)")
            return

        if file_path and not query:
            results = indexer.list_symbols_by_file(file_path, limit=limit)
            if not results:
                click.echo(f"No symbols in '{file_path}'.")
                return
            click.echo(f"{len(results)} symbol(s) in {file_path}:")
            for r in results:
                sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                click.echo(f"  [{r['id']}] {r['symbol_name']} ({r['symbol_type'][:4]}){sig}")
            return

        if not query:
            browse = indexer.list_symbols(limit=limit)
            click.echo(f"{len(browse)} symbol(s):")
            for r in browse:
                loc = _fmt_loc(r['file_path'], r['start_line'])
                click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}) {r['symbol_type'][:4]}")
            return

        # Try exact match first
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
                click.echo(f"Multiple '{query}':")
                for s in symbols:
                    loc = _fmt_loc(s['file_path'], s['start_line'])
                    click.echo(f"  [{s['id']}] {s['symbol_name']} ({loc})")
                return

        if sym:
            callers = indexer.get_callers(sym['symbol_name'])
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            loc = _fmt_loc(sym['file_path'], sym['start_line'])
            click.echo(f"{sym['symbol_name']} ({loc}) {sym['language']}")
            if sym.get('signature'):
                click.echo(f"  sig: {sym['signature']}")
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10])
                click.echo(f"  callers: {cstr}")
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
                click.echo(f"  calls: {cstr}")
            return

        # Fall through to search
        results = indexer.search_symbols(query, limit=limit, use_regex=regex)
        if not results:
            click.echo(f"No match for '{query}'.")
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("query")
@click.argument('search')
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=20, type=int, help='Max results')
@click.option('--kind', help='Filter by symbol type (function, class, method, etc.)')
@click.option('--regex', is_flag=True, help='Interpret query as Python regex')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_query(search, root, limit, kind, regex, as_json):
    """Search for symbols in the codebase."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.search_symbols(search, limit=limit, use_regex=regex)
        if kind:
            results = [r for r in results if r.get('symbol_type') == kind]
        if not results:
            click.echo(f"No match for '{search}'.")
            return
        if as_json:
            import json
            click.echo(json.dumps(results, indent=2, default=str))
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("explore")
@click.argument('query')
@click.option('--root', default='.', help='Project root directory')
@click.option('--max-files', default=3, type=int, help='Max files to show source from')
def code_explore(query, root, max_files):
    """Explore an area: relevant symbols' source + call paths in one shot."""
    import os
    from indexer import CodeIndexer, CODE_DB_FILENAME
    root_path = os.path.abspath(root)
    db_path = os.path.join(root_path, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index at {db_path}. Run `mem code init` first.")
        return
    indexer = CodeIndexer(root_path)
    try:
        symbols = indexer.search_symbols(query, limit=10)
        if not symbols:
            click.echo(f"No matches for '{query}'.")
            return
        shown_files = set()
        for sym in symbols[:10]:
            loc = _fmt_loc(sym['file_path'], sym['start_line'])
            click.echo(f"\n── {sym['symbol_name']} ({loc}) {sym['symbol_type']} ──")
            if sym.get('signature'):
                click.echo(f"  sig: {sym['signature']}")
            callers = indexer.get_callers(sym['symbol_name'])
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:5])
                click.echo(f"  callers: {cstr}")
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:5])
                click.echo(f"  calls: {cstr}")
            # Show source code
            if sym['file_path'] not in shown_files and len(shown_files) < max_files:
                shown_files.add(sym['file_path'])
                abs_fp = os.path.join(root_path, sym['file_path'])
                if os.path.isfile(abs_fp):
                    lines = open(abs_fp).read().splitlines()
                    start = max(0, sym['start_line'] - 2)
                    end = min(len(lines), sym['end_line'] + 1)
                    click.echo(f"  source ({sym['start_line']}-{sym['end_line']}):")
                    for i in range(start, end):
                        marker = "→" if start + i == sym['start_line'] - start else " "
                        click.echo(f"    {marker} L{sym['start_line'] - start + i}: {lines[start + i]}")
    finally:
        indexer.close()


@code.command("files")
@click.option('--root', default='.', help='Project root directory')
@click.option('--prefix', default='', help='Filter to files matching this prefix')
@click.option('--limit', default=100, type=int, help='Max files to show')
@click.option('--tree', is_flag=True, help='Show as tree (default: flat list)')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_files(root, prefix, limit, tree, as_json):
    """Show project file structure from the index."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        files = indexer.list_files(prefix=prefix, limit=limit)
        if not files:
            click.echo("No files in index.")
            return
        if as_json:
            import json
            click.echo(json.dumps(files, indent=2, default=str))
            return
        if tree:
            # Simple tree view
            tree_data = {}
            for f in files:
                parts = f['file_path'].split('/')
                node = tree_data
                for p in parts:
                    node = node.setdefault(p, {})
            def _print_tree(d, indent=""):
                for k, v in sorted(d.items()):
                    is_leaf = not v
                    click.echo(f"{indent}{'📄 ' if is_leaf else '📁 '}{k}")
                    if not is_leaf:
                        _print_tree(v, indent + "  ")
            _print_tree(tree_data)
        else:
            total = len(files)
            click.echo(f"{total} file(s):")
            for f in files:
                click.echo(f"  {f['file_path']} ({f['symbol_count']}s)")
    finally:
        indexer.close()


@code.command("impact")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--depth', default=2, type=int, help='Traversal depth')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_impact(symbol_name, root, depth, as_json):
    """Analyze what code is affected by changing a symbol."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_impact(symbol_name, depth=depth)
        if not results:
            click.echo(f"No impact found for '{symbol_name}'.")
            return
        if as_json:
            import json
            click.echo(json.dumps(results, indent=2, default=str))
            return
        click.echo(f"Impact analysis for '{symbol_name}' (depth={depth}):\n")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            via = f" (via {r['via']})" if r.get('via') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}:{r['line_number']}){via}")
    finally:
        indexer.close()


@code.command("status")
@click.option('--root', default='.', help='Project root directory')
def code_status(root):
    """Show code graph indexing stats for a project."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code indexed. Run `kb code init` first.")
            return
        click.echo(f"{stats.get('name', '?')}: {stats['file_count']}f {stats['symbol_count']}s {stats.get('edges', 0)}e")
    finally:
        indexer.close()


@code.command("list-projects")
@click.option('--search-root', default='', help='Comma-separated paths to scan (default: ~,/mnt,/media,/opt)')
def code_list_projects(search_root):
    """Scan for all indexed projects on the system."""
    from indexer.indexer import find_code_projects
    projects = find_code_projects(search_root)
    if not projects:
        click.echo("No indexed projects found.")
        return
    click.echo(f"\nFound {len(projects)} project(s):\n")
    for p in sorted(projects, key=lambda x: x["name"]):
        click.echo(f"  {p['name']}")
        click.echo(f"    Root: {p['root']}")
        click.echo(f"    Symbols: {p['symbols']}  Files: {p['files']}")


# ── End Code Graph commands ─────────────────────────────────

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
    from .main import cli
    cli(prog_name='mem')
