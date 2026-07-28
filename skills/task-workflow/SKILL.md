---
name: task-workflow
description: Create, list, update, and block tasks on a planet
tools: [task_create, task_list, task_update, task_block, logInteraction]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `task_create` | `topic`, `title`, `priority` |
| 2 | `task_list` | `topic` — verify after create/update |
| 3 | `task_update` | `task_id`, `status` |
| 4 | `task_block` | `task_id`, `reason` — creates linked issue note |

Always `task_list` after create/update to confirm status.
