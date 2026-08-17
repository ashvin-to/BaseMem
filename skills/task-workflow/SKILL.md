---
name: task-workflow
description: "Manage planet task lifecycle — creation, listing, status updates, and blocker issues. Triggers on: create task, list tasks, task status, block task, task dependency."
---

# Task Lifecycle Protocol

Track work items, dependencies, and blocking issues on BaseMem planets.

## Workflow

| Step | Tool | Input | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `task_create` | `topic`, `title`, `priority` | Register new task item ($\le 20$ words description) |
| 2 | `task_list` | `topic` | Verify task creation and retrieve task IDs |
| 3 | `task_update` | `task_id`, `status` | Update task state (`pending`, `in_progress`, `completed`) |
| 4 | `task_block` | `task_id`, `reason` | Flag task as blocked and generate linked issue note |

## Rules

1. **Verify State**: Always run `task_list` after creating or updating tasks to verify current state.
2. **Concise Tasks**: Keep task titles to single concise sentences ($\le 20$ words).
3. **Blockers**: Call `task_block` when blocked; it automatically logs an issue note for the team.
