"""Session CLI: active planet, turns, archives."""

import json
from pathlib import Path

import click


@click.group()
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
    root_name = _get_project_root()
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])

    sun_node = manager.get_or_create_folder_hub(root_name)
    click.echo(f"\n[SUN] ROOT HUB: {sun_node.title}")

    cursor = ctx.obj['storage'].connection.cursor()
    rows = cursor.execute(
        "SELECT topic, display_topic, status, goal, current_state, next_steps, updated_at FROM planets ORDER BY updated_at DESC"
    ).fetchall()
    click.echo("\n[PLANETS] ACTIVE PLANETS (TASKS):")
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
    root_name = _get_project_root()
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
    root_name = _get_project_root()
    import glob
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
        if not files:
            return
        chat_file = max(files, key=lambda p: Path(p).stat().st_mtime)
    try:
        transcript = f"Full Archive of {topic}\n"
        if chat_file.endswith(".jsonl"):
            with open(chat_file) as f:
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
            with open(chat_file) as f:
                data = json.load(f)
            msgs = data.get("messages") or data.get("conversation") or data.get("items") or [data] if isinstance(data, dict) else data
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
        if node:
            click.echo("[ok] History Archived.")
        else:
            click.echo(f"[!] Archive ignored: No active planet for '{topic}'.")
    except Exception as e:
        click.echo(f"Sync failed: {e}")


@session.command()
@click.argument('node_id', required=False)
@click.option('--topic', '-t', help='Read a planet by topic instead of node id')
@click.pass_context
def read(ctx, node_id, topic):
    """Read a planet, node, or session details.

    If node_id is a number, reads a session. If --topic is set, reads a planet.
    Otherwise reads a node by its id string."""
    from storage.sessions import SessionManager
    import json as _json
    manager = SessionManager(ctx.obj['storage'])
    if topic:
        node = manager.get_planet(topic)
        if node:
            click.echo(f"\n{node.title}:\n\n{node.content}")
        else:
            click.echo("Planet not found.")
    elif node_id and node_id.isdigit():
        sid = int(node_id)
        session = manager.get_session(sid)
        if not session:
            click.echo(f"Session {sid} not found.")
            return
        click.echo(f"Session: {session.get('title', 'untitled')} (id={sid})")
        click.echo(f"  topic: {session.get('topic', '?')}")
        click.echo(f"  status: {session.get('status', '?')}")
        click.echo(f"  agent: {session.get('agent_id', '?')}")
        click.echo(f"  started: {session.get('started_at', '?')}")
        click.echo(f"  last active: {session.get('last_active_at', '?')}")
        if session.get("ended_at"):
            click.echo(f"  ended: {session['ended_at']}")
        if session.get("summary"):
            click.echo(f"  summary: {session['summary']}")
        note_ids = _json.loads(session.get("note_ids", "[]"))
        if note_ids:
            click.echo(f"  notes ({len(note_ids)}):")
            ph = ",".join("?" for _ in note_ids)
            cursor = ctx.obj['storage'].connection.cursor()
            for r in cursor.execute(
                f"SELECT id, kind, title, content FROM notes WHERE id IN ({ph}) ORDER BY id ASC",
                note_ids,
            ):
                t = r["title"] or r["content"][:80]
                click.echo(f"    note-{r['id']} [{r['kind']}] {t[:200]}")
        task_ids = _json.loads(session.get("task_ids", "[]"))
        if task_ids:
            click.echo(f"  tasks ({len(task_ids)}):")
            ph = ",".join("?" for _ in task_ids)
            cursor = ctx.obj['storage'].connection.cursor()
            for r in cursor.execute(
                f"SELECT id, status, priority, title FROM tasks WHERE id IN ({ph}) ORDER BY id ASC",
                task_ids,
            ):
                click.echo(f"    task-{r['id']} [{r['status']}/{r['priority']}] {r['title']}")
    else:
        node = ctx.obj['storage'].get_node(node_id) if node_id else None
        if node:
            click.echo(f"\n{node.title}:\n\n{node.content}")
        else:
            click.echo("Node not found.")


@session.command()
@click.argument('topic')
@click.argument('title')
@click.option('--agent-id', default='default', help='Agent identifier')
@click.pass_context
def start(ctx, topic, title, agent_id):
    """Start a new session on a planet."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    sid = manager.create_session(topic, title, agent_id)
    click.echo(f"Session created: id={sid}, topic='{topic}', title='{title}', agent='{agent_id}'.")


@session.command()
@click.argument('session-id', type=int)
@click.option('--summary', '-s', help='Optional closing summary')
@click.pass_context
def end(ctx, session_id, summary):
    """End (close) a session."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok = manager.close_session(session_id, summary=summary)
    if not ok:
        click.echo(f"Session {session_id} not found.")
        return
    session = manager.get_session(session_id)
    click.echo(f"Session {session_id} closed. Status: {session['status']}.")
    if session.get("summary"):
        click.echo(f"Summary: {session['summary']}")


@session.command()
@click.argument('session-id', type=int)
@click.pass_context
def pause(ctx, session_id):
    """Pause a session."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok = manager.pause_session(session_id)
    if not ok:
        click.echo(f"Session {session_id} not found.")
        return
    click.echo(f"Session {session_id} paused.")


@session.command()
@click.argument('session-id', type=int)
@click.option('--agent-id', default='default', help='New agent identifier')
@click.pass_context
def resume(ctx, session_id, agent_id):
    """Resume a paused session."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    ok = manager.resume_session(session_id, agent_id)
    if not ok:
        click.echo(f"Session {session_id} not found.")
        return
    click.echo(f"Session {session_id} resumed. Agent: {agent_id}.")


@session.command(name='list')
@click.option('--topic', '-t', help='Filter by planet topic')
@click.option('--status', '-s', help='Filter by status (active, paused, closed)')
@click.pass_context
def list_sessions(ctx, topic, status):
    """List sessions, optionally filtered by topic and/or status."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    if topic:
        sessions = manager.list_sessions(topic, status=status)
    else:
        sessions = []
        for p in manager.list_planets():
            sessions.extend(manager.list_sessions(p["topic"], status=status))
    if not sessions:
        click.echo("No sessions found.")
        return
    click.echo(f"Sessions ({len(sessions)}):")
    for s in sessions:
        title = s.get("title", "untitled")
        st = s.get("status", "?")
        agent = s.get("agent_id", "?")
        last = s.get("last_active_at", "?")[:19]
        click.echo(f"  id={s['id']} '{title}' [{st}] agent={agent} last={last}")


def _get_project_root():
    """Find the nearest project root (folder with AGENTS.md, .git, or fallback to current)"""
    curr = Path.cwd().absolute()
    for parent in [curr] + list(curr.parents):
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent.name
    return curr.name
