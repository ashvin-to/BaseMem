---
name: using-basemem
description: Core memory protocol — context, decisions, session lifecycle
tools: [getContext, logInteraction, update_planet]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `getContext` | `topic="repo-name"`, optional `query` |
| 2 | `logInteraction` | `topic`, `decision="..."` or `fact="..."` |
| 3 | `logInteraction` | `topic`, `summary="..."`, `activity="done"` |

Skip `getContext` if memory context is already injected. Always pass `topic` explicitly.
