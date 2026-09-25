---
name: using-basemem
description: "BaseMem memory + code intelligence protocol. Triggers on: recall context, log decision, session lifecycle, code search, review blast radius, task management, planet memories, zero-RAM code graph."
---

# BaseMem — Memory + Code Intelligence Protocol

BaseMem provides persistent cross-session memory (planets, notes, decisions) and zero-RAM code intelligence.

## Quick Decision Matrix

| Task | Preferred Tool Call |
| :--- | :--- |
| Recall session / topic context (mid-session refresh or topic switch ONLY — never at session start) | `getContext(topic="repo-name")` |
| FIRST step for ANY code question, bug, or exploration (before Read/Grep/Glob) | `code_find(query="...")` |
| Fast text search (instead of grep) | `code_find(query="...", grep=True)` |
| Read source code window (STEP 2, after code_find) | `code_read(filePath="...", offset=1, limit=50)` |
| Explore code structure | `code_explore(path="...")` |
| Code review blast-radius | `get_review_context(files=["a.py"])` |
| Log key decision / architectural fact | `logInteraction(topic="...", decision="...")` |
| Create / list task items | `task_create(...)` / `task_list(...)` |
| End session & save summary | `logInteraction(topic="...", summary="...", activity="done")` |

## Workflow

1. **Session Start**: Context is auto-injected — do NOT call `getContext`. Only call it mid-session to refresh or switch topics.
2. **Code task? Call `code_find` FIRST, before any Read/Grep/Glob.** Then `code_read` (limit<=50) for windows, `code_explore` for callers, `code_files` for listing. If `code_find` returns empty, call `code_init(projectRoot)` once and retry. Never start with a full-file read.
3. **Decision/fix/fact? Call `logInteraction(topic, decision="...")` IMMEDIATELY** — the same turn you decided, not at session end.
4. **Session End**: Call `logInteraction(topic="...", summary="...", activity="done")` when finishing work.

## Code Intelligence Rules

- **Prefer `code_find` over `code_read`**: Returns line numbers only (~0 extra context tokens).
- **Tight Reads**: Keep `code_read` window sizes small (`limit <= 50 lines`).
- **Initial Indexing**: If `code_find` returns empty results, run `code_init(repo_path="...")` first.

## Gotchas

1. Avoid full-file reads unless strictly necessary — use `code_find` and `code_read` line slicing.
2. Always pass the exact `topic` (repository folder name) when logging decisions.
3. Keep `task_create` descriptions to single concise sentences ($\le 20$ words).
