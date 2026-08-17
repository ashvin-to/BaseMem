---
name: session-start
description: "Initialize or resume a session on a BaseMem planet. Triggers on: session start, resume session, bootstrap context, load topic memory."
---

# Session Bootstrap Protocol

Initialize or resume session tracking for a specific topic planet.

## Workflow

| Step | Tool | Input | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `session_start` | `topic`, `title`, `agent_id`, optional `session_id` | Initialize / attach agent session to topic |
| 2 | `logInteraction` | `topic`, `currentState="..."`, `nextStep="..."` | Record initial focus & state |

## Rules

1. **Auto-Injected Context**: Skip `session_start` if memory context is already injected at turn start.
2. **Session Resumption**: Pass `session_id` to attach to a previous active session on the topic planet.
