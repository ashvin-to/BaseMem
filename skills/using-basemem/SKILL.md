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
| Evidence gate | `verify_change(projectRoot="...", files=[...], artifact_paths=[...], test_command="...")` |
| Log key decision / architectural fact | `logInteraction(topic="...", decision="...")` |
| Create / list task items | `task_create(...)` / `task_list(...)` |
| End session & save summary | `logInteraction(topic="...", summary="...", activity="done")` |

## Workflow

1. **Session Start**: Context is auto-injected — do NOT call `getContext`. Only call it mid-session to refresh or switch topics.
2. **Choose the lightest path**: For a known target, inspect the exact file and nearby tests/callers directly. For unfamiliar or cross-file work, Call code_find FIRST (`code_find`).
3. **Literal values**: Use `code_find(query="...", grep=True)` for CLI flags, JSON keys, shell commands, documentation, and config values. The code graph is for symbols and relationships, not universal text search.
4. **Reindex when needed**: If `code_find` is empty, call `code_init(projectRoot)` once and retry. Reindex after multiple symbol/signature additions, renames, or stale results.
5. **Keep the loop short**: For ordinary small tasks, use `code_find` → `code_init` if empty/stale → `code_read` exact source → inspect artifacts → run focused tests; use `verify_change` for an explicit evidence bundle. Trace callers or review impact only when behavior depends on them.
6. **Separate evidence**: Memory preserves why and durable constraints; source, artifacts, and tests establish current behavior. Memory is context, not verification. Label conclusions as memory, source, artifact, test, or inference.
7. **Log selectively**: Call `logInteraction(topic, decision="...")` immediately for meaningful decisions, fixes, and corrections. Do not log routine observations.
8. **Session End**: Call `logInteraction(topic="...", summary="...", activity="done")` when finishing work.

## Code Intelligence Rules

- **Use the graph for structure**: `code_find` for symbols, `code_explore` for callers/callees, and `get_review_context` for impact.
- **Use direct source for current truth**: inspect a known file before broad graph exploration; keep reads tight (`limit <= 50 lines`).
- **Use text search for literals**: `code_find(query="...", grep=True)` is appropriate for flags, JSON fields, commands, docs, and embedded strings.
- **Reindex after structural churn**: run `code_init` when search is empty or stale after multiple symbol/signature changes.

## Gotchas

1. Avoid full-file reads unless strictly necessary — use `code_find` and `code_read` line slicing.
2. Always pass the exact `topic` (repository folder name) when logging decisions.
3. Keep `task_create` descriptions to single concise sentences ($\le 20$ words).
