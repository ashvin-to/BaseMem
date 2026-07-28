---
name: session-start
description: Initialize or resume a session on a planet
tools: [session_start, logInteraction]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `session_start` | `topic`, `title`, `agent_id`, optional `session_id` |
| 2 | `logInteraction` | `topic`, `currentState="..."`, `nextStep="..."` |

Skip if memory context already injected. Pass `session_id` to resume existing sessions.
