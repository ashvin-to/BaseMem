"""Main CLI entry point — registers all subcommand groups."""

import json
import logging
import sqlite3
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


# ── Top-level commands ──

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
        active = manager.get_active_planet()
        resolved_topic = active.metadata.get("display_topic") or active.metadata.get("topic") or active.title if active else root_name

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
