---
name: task-workflow
description: Task creation, listing, status updates, and blocking for structured work tracking
tools: [task_create, task_list, task_update, task_block, logInteraction]
---

## When to use this skill
Use this skill to create and track work items across multi-step features, refactors, or bug fixes on a planet.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `task_create(topic, title, priority)` | `topic="repo-name"`, `title="..."`, `priority="high"` | New task ID (e.g. `task-12`) |
| 2 | `task_list(topic)` | `topic="repo-name"` | Overview of all tasks and status on planet |
| 3 | `task_update(task_id, status)` | `task_id=12`, `status="in_progress"` | Updated task status |
| 4 | `task_block(task_id, reason)` | `task_id=12`, `reason="Waiting on PR"` | Blocked task status with linked issue note |
| 5 | `logInteraction(topic, ...)` | `topic="repo-name"`, `currentState="..."` | Planet state updated with task progress |

## Example

```python
# Step 1: Create work item
task_create(topic="basemem", title="Add get_review_context tool", priority="high")

# Step 2: List open tasks
task_list(topic="basemem")

# Step 3: Update status to completed
task_update(task_id=1, status="completed")

# Step 4: Log progress
logInteraction(topic="basemem", currentState="Completed task-1: get_review_context tool implemented.")
```

## Notes
Always list tasks after creation or update to verify status. If a task becomes blocked, call `task_block` with an explicit reason to automatically log an issue note on the planet.
