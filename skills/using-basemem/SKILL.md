---
name: using-basemem
description: BaseMem core memory protocol for tracking context, decisions, and session lifecycle
tools: [getContext, logInteraction, update_planet]
---

## When to use this skill
Use this skill at session start, during major decisions, or at session end to maintain persistent agent context across turns and sessions.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `getContext(topic, query)` | `topic="repo-name"`, optional `query` | Pre-digested memory context (decisions, state, notes) |
| 2 | `logInteraction(topic, ...)` | `topic="repo-name"`, `decision="..."`, `fact="..."` | Persisted interaction note on planet |
| 3 | `logInteraction(topic, summary=...)` | `topic="repo-name"`, `summary="..."`, `activity="done"` | Session end summary logged |

## Example

```python
# Context is injected by hook at session start. If switching topics mid-session:
getContext(topic="basemem", query="auth refactor")

# During work after making a key architectural choice:
logInteraction(topic="basemem", decision="Using tree-sitter for AST symbol resolution.")

# At session end:
logInteraction(topic="basemem", summary="Completed tree-sitter integration for Python and TypeScript files.", activity="done")
```

## Notes
Do not call `getContext` at session start if memory context is already injected in your system prompt. Only call `getContext` mid-session if switching topics or needing a fresh query lookup. Always pass `topic` explicitly.
