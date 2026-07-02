"""Note CLI: create, link, and manage notes on a planet."""

import click


@click.group()
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
    root_name = _get_project_root()
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
@click.option('--type', 'link_type', default='related', help='Link type: related|depends|implements|fixes|duplicates|supersedes|causes|blocks|tests|references')
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


def _get_project_root():
    """Find the nearest project root (folder with AGENTS.md, .git, or fallback to current)"""
    from pathlib import Path
    curr = Path.cwd().absolute()
    for parent in [curr] + list(curr.parents):
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent.name
    return curr.name
