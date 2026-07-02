"""Edge CLI: decay and prune auto-links."""

import click


@click.group()
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
