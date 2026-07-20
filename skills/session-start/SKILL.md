---
name: session-start
description: Initialize or resume an active session on a planet at workflow start
tools: [session_start, logInteraction]
---

## When to use this skill
Use this skill when starting a new unit of work or resuming a paused task session on a planet.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `session_start(topic, title, agent_id, session_id)` | `topic="repo-name"`, `title="Sprint 1"`, `agent_id="claude"`, optional `session_id=42` | Active session ID (new or resumed) |
| 2 | `logInteraction(topic, ...)` | `topic="repo-name"`, `currentState="..."`, `nextStep="..."` | Planet state updated with session goal |

## Example

```python
# Create a new session on planet 'basemem'
session_start(topic="basemem", title="Add Skills System", agent_id="claude")

# Or resume an existing session (ID 42)
session_start(topic="basemem", title="Add Skills System", agent_id="claude", session_id=42)

# Log initial plan
logInteraction(topic="basemem", currentState="Starting skills system creation", nextStep="Write skill markdown files")
```

## Notes
Do not call `getContext` at session start — memory context was already injected by the SessionStart hook unless you are switching topics. If a session is already active on the planet, pass `session_id` to resume it instead of creating duplicate sessions.
