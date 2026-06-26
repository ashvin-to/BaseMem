# Tasks

A Task is a **distinct entity** from a Note, not a kind of Note.

| | Task | Note |
|---|---|---|
| **Purpose** | Actionable work item with workflow state | Everything else — decisions, facts, context |
| **State** | Status lifecycle (todo → in_progress → blocked/done) | Immutable record |
| **Relations** | Explicit dependency graph (`depends_on`) | Semantic similarity links (`note_links`) |
| **Tracking** | Priority, files, referenced notes | Kind, tags, pinned |

A task may reference notes through its `notes` field; a note should **not** duplicate task status.

### Fields

| Field | Type | Description |
|---|---|---|
| `id` | int | Auto-increment primary key |
| `topic` | str | Planet topic (matching the `notes.topic` convention) |
| `title` | str | Task summary |
| `status` | str | One of `todo`, `in_progress`, `blocked`, `done` |
| `priority` | str | One of `low`, `medium`, `high` |
| `depends_on` | list[int] | Task IDs that must complete first |
| `files` | list[str] | File paths relevant to this task |
| `notes` | list[int] | Note IDs referenced by this task |
| `created_at` | str | ISO-8601 timestamp |
| `completed_at` | str or null | Set when status becomes `done` |

### Schema

`tasks` table in `basemem.db`. `depends_on`, `files`, `notes` are stored as JSON arrays in TEXT columns.

### Dependency cycle prevention

`update_task` runs a depth-first check before accepting `depends_on` changes. A cycle is detected when any transitive dependency eventually references the task being updated.

### Integration with compaction

`compact_planet` preserves any note whose ID appears in the `notes` list of a **non-done** task. Notes referenced exclusively by `done` tasks follow normal compaction rules (only pinned + recent survive).

### CLI

```
mem task create <topic> <title> [--priority] [--depends-on] [--files] [--notes]
mem task set <task_id> [--status] [--priority]
mem task block <task_id> [--reason]
mem task done <task_id>
mem task list [--topic] [--status] [--priority]
```

### MCP tools

- `task_create(topic, title, priority, depends_on, files, notes)` — returns task id
- `task_update(task_id, status, priority, files, notes)`
- `task_list(topic, status, priority)`
- `task_block(task_id, reason)` — sets status=blocked; if reason given, creates an issue note
