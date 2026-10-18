---
name: using-basemem
description: "BaseMem memory + code intelligence protocol. Triggers on: recall context, log decision, session lifecycle, code search, review blast radius, project memory, zero-RAM code graph."
---

# BaseMem — Memory + Code Intelligence Protocol

BaseMem provides persistent cross-session memory (planets, notes, decisions) and zero-RAM code intelligence.

## Quick Decision Matrix

| Task | Preferred Tool Call |
| :--- | :--- |
| Recall session / topic context (mid-session refresh or topic switch ONLY — never at session start) | `getContext(topic="repo-name")` |
| Structural symbol discovery (when the graph helps) | `code_find(query="...")` |
| Callers / callees / blast radius | `code_explore(query="...")` |
| Read source (ordinary inspection) | native `Read` |
| Literal text search | native `grep`/`rg` |
| File enumeration | native `glob`/`ls` |
| Code review blast-radius | `get_review_context(files=["a.py"])` |
| Evidence gate | `verify_change(projectRoot="...", files=[...], artifact_paths=[...], test_command="...")` |
| Log key decision / architectural fact | `logInteraction(topic="...", decision="...")` |
| End session & save summary | `logInteraction(topic="...", summary="...", activity="done")` |

**Division of labor:** structural discovery (symbols, callers/callees, impact) → BaseMem. Ordinary source inspection and literal search → native tools. `code_read` and `code_find(grep=True)` are deprecated; prefer native `Read` and native `grep`/`rg`.

## Workflow

1. **Session Start**: Context is auto-injected — do NOT call `getContext`. Only call it mid-session to refresh or switch topics.
2. **Choose the lightest path**: For a known target, inspect the exact file and nearby tests/callers directly with native tools. For unfamiliar or cross-file structural work, use `code_find` for symbols and `code_explore` for callers/callees.
3. **Literal values**: Use native `grep`/`rg` for CLI flags, JSON keys, shell commands, documentation, and config values. The code graph is for symbols and relationships, not universal text search.
4. **Reindex when needed**: If `code_find` is empty, call `code_init(projectRoot)` once and retry. Reindex after multiple symbol/signature additions, renames, or stale results.
5. **Keep the loop short**: For ordinary small tasks, discover → read exact source with native `Read` → inspect artifacts → run focused tests; use `verify_change` for an explicit evidence bundle. Trace callers or review impact only when behavior depends on them.
6. **Separate evidence**: Memory preserves why and durable constraints; source, artifacts, and tests establish current behavior. Memory is context, not verification. Label conclusions as memory, source, artifact, test, or inference.
7. **Log selectively**: Call `logInteraction(topic, decision="...")` immediately for meaningful decisions, fixes, and corrections. Do not log routine observations.
8. **Session End**: Call `logInteraction(topic="...", summary="...", activity="done")` when finishing work.

## Code Intelligence Rules

- **Use the graph for structure**: `code_find` for symbols, `code_explore` for callers/callees, and `get_review_context` for impact.
- **Use direct source for current truth**: inspect a known file with native `Read` before broad graph exploration.
- **Use text search for literals**: native `grep`/`rg` is preferred for flags, JSON fields, commands, docs, and embedded strings.
- **Reindex after structural churn**: run `code_init` when search is empty or stale after multiple symbol/signature changes.
- **Two tools are deprecated**: `code_read` (use native `Read`) and `code_find(grep=True)` (use native `grep`/`rg`). They remain for backward compatibility only.

## Gotchas

1. Avoid full-file reads unless strictly necessary — use `code_find` and `code_read` line slicing.
2. Always pass the exact `topic` (repository folder name) when logging decisions.
