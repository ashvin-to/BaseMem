---
name: using-basemem
description: "BaseMem memory + code intelligence protocol. Triggers on: recall context, log decision, session lifecycle, code search, review blast radius, task management, planet memories, zero-RAM code graph."
---

# BaseMem — Memory + Code Intelligence Protocol

BaseMem provides persistent cross-session memory (planets, notes, decisions) and zero-RAM code intelligence.

## Quick Decision Matrix

| Task | Preferred Tool Call |
| :--- | :--- |
| Recall session / topic context | `getContext(topic="repo-name")` |
| Fast code search (line-level) | `code_find(query="...", grep=True)` |
| Read source code window | `code_read(path="...", offset=1, limit=50)` |
| Explore code structure | `code_explore(path="...")` |
| Code review blast-radius | `get_review_context(files=["a.py"])` |
| Log key decision / architectural fact | `logInteraction(topic="...", decision="...")` |
| Create / list task items | `task_create(...)` / `task_list(...)` |
| End session & save summary | `logInteraction(topic="...", summary="...", activity="done")` |

## Memory & Context Workflow

1. **Session Start**: Context is auto-injected. Skip `getContext` unless switching topics or refreshing context.
2. **Logging Decisions**: Keep facts $\le 30$ words; record essential architectural decisions immediately via `logInteraction(topic, decision="...")`.
3. **Session End**: Call `logInteraction(topic="...", summary="...", activity="done")` when finishing work.

## Code Intelligence Rules

- **Prefer `code_find` over `code_read`**: Returns line numbers only (~0 extra context tokens).
- **Tight Reads**: Keep `code_read` window sizes small (`limit <= 50 lines`).
- **Initial Indexing**: If `code_find` returns empty results, run `code_init(repo_path="...")` first.

## Gotchas

1. Avoid full-file reads unless strictly necessary — use `code_find` and `code_read` line slicing.
2. Always pass the exact `topic` (repository folder name) when logging decisions.
3. Keep `task_create` descriptions to single concise sentences ($\le 20$ words).
