"""Main CLI interface using Click (Full Search Version)"""

import click
import asyncio
import json
from pathlib import Path
import logging
import os
import sys

from storage.db import StorageManager
from graph.engine import GraphEngine
from orchestrator.context import ContextOrchestrator
from processing.pipeline import ProcessingPipeline
from visualization.terminal import TerminalGraphVisualizer
from modelsimport NodeType, EdgeType

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

    # Notes
    for r in conn.execute(
        "SELECT topic, kind, content, created_at FROM notes WHERE content LIKE ? OR title LIKE ?",
        (like, like),
    ):
        preview = r["content"][:150].replace("\n", " ").strip()
        label = f"{r['topic']} / {r['kind']}"
        results.append(("note", label, f"note-{r['id']}", preview))

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

@cli.command()
@click.option('--background', '-b', is_flag=True, help='Run in bg')
@click.pass_context
def serve(ctx, background, port=5000):
    import subprocess
    if background:
        log = Path.home() / ".basemem" / "server.log"
        click.echo(f"[*] Galaxy active in background. Port {port}")
        with open(log, "a") as f:
            subprocess.Popen([sys.executable, str(Path(__file__).parent.parent.parent.parent / "kb.py"), "serve"], stdout=f, stderr=f, start_new_session=True)
        return
    from serverimport app
    click.echo(f"[*] Galaxy active on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

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
        patterns = [
            f"/home/zoro/.gemini/tmp/*/chats/session-*-{agent_id}.json",
            f"/home/zoro/.codex/sessions/**/rollout-*-{agent_id}.jsonl",
            f"/home/zoro/.claude/**/*.json*",
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
@click.pass_context
def planet_compact(ctx, topic, agent_id):
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.compact_planet(root_name, topic, agent_id=agent_id)
    click.echo(f"[ok] Planet compacted: {node.title}")

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

@cli.command()
@click.argument('topic')
@click.option('--type', 'kind', default='fact', help='decision, fact, task, issue, question, concept, example')
@click.option('--message', '-m', required=True)
@click.option('--title')
@click.option('--status', default='open')
@click.option('--agent-id', default='default')
@click.pass_context
def note(ctx, topic, kind, message, title, status, agent_id):
    """Add a typed collaboration note linked to a planet."""
    root_name = get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    node = manager.add_note(root_name, topic, kind, message, agent_id=agent_id, title=title, status=status)
    click.echo(f"[ok] Note added: {node['title']} ({node['id']})")

@cli.command()
@click.argument('doc_name', required=False)
@click.pass_context
def docs(ctx, doc_name):
    base = Path(__file__).parent.parent.parent.parent.absolute()
    m = {"readme": "README.md", "implementation": "IMPLEMENTATION.md", "development": "DEVELOPMENT.md", "agents": "AGENTS.md"}
    if not doc_name: click.echo("Available: " + ", ".join(m.keys())); return
    path = base / m.get(doc_name.lower(), "")
    if path.exists(): click.echo(open(path).read())

if __name__ == '__main__':
    from basemem.cli import cli
    cli(prog_name='mem')
