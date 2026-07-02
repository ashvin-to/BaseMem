"""Planet CLI: manage shared task planets."""

import click


@click.group()
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
    root_name = _get_project_root()
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
    root_name = _get_project_root()
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
    root_name = _get_project_root()
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
@click.option('--relation', default='related', help='Relation: related|depends|implements|fixes|duplicates|supersedes|causes|blocks|tests|references')
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
    for link in links:
        click.echo(f"  {link['planet']} [{link['relation']}] (w={link['weight']})")


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


def _get_project_root():
    """Find the nearest project root (folder with AGENTS.md, .git, or fallback to current)"""
    from pathlib import Path
    curr = Path.cwd().absolute()
    for parent in [curr] + list(curr.parents):
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent.name
    return curr.name
