"""Edge CLI: maintain auto-links (decay and/or prune)."""

import click


@click.group()
def edge():
    """Manage edge lifecycle: decay and prune."""
    pass


@edge.command("maintain")
@click.option('--decay-factor', type=float, help='Multiply all auto-link weights by this factor')
@click.option('--prune-threshold', type=float, help='Remove auto-links below this weight')
@click.option('--planet', help='Limit to a specific planet')
@click.pass_context
def edge_maintain(ctx, decay_factor, prune_threshold, planet):
    """Apply decay and/or prune to auto-links. Decay runs before prune so pruning reflects decayed weights. At least one of --decay-factor or --prune-threshold must be provided."""
    from storage.sessions import SessionManager
    manager = SessionManager(ctx.obj['storage'])
    msg = manager.edge_maintain(planet=planet, decay_factor=decay_factor, prune_threshold=prune_threshold)
    click.echo(msg)
