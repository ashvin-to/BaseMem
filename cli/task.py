"""Task CLI: create, update, block, and list tasks."""

import json

import click


@click.group()
def task():
    """Manage tasks with dependency tracking and workflow state."""
    pass


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
