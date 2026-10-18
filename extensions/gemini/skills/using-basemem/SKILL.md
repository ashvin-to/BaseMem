---
name: using-basemem
description: BaseMem memory protocol
---

If context was injected at session start, do not call getContext. Otherwise call `getContext(topic)` once.

## Topic = project folder name (never generic)

| Step | Tool | When |
|------|------|------|
| Start | `getContext(topic, query)` | Only mid-session refresh or topic switch |
| During | `logInteraction(topic, decision=, fact=)` | Every non-trivial decision |
| End | `logInteraction(topic, summary=, activity="done")` | Session end |

## Code — structural discovery via BaseMem; ordinary inspection via native tools

| Task | Tool |
|------|------|
| Find symbol | `code_find('sym')` (BaseMem) |
| Callers/callees/blast radius | `code_explore('sym')` (BaseMem) |
| Read file | native `Read` |
| Literal text search | native `grep`/`rg` |
| File enumeration | native `glob`/`ls` |

`code_read` and `code_find(grep=True)` are deprecated; prefer native `Read` and native `grep`/`rg`. For a known target, inspect the exact file and nearby tests/callers. For unfamiliar or cross-file work, use `code_find` for symbols and `code_explore` for callers/callees. If `code_find` is empty, call `code_init(projectRoot)` once and retry.

Keep small tasks to discovery → exact source read with native Read → artifact inspection → focused tests, using `verify_change` for an explicit evidence bundle. Memory preserves why and durable constraints; source, artifacts, and tests establish current behavior. Memory is context, not verification. Label conclusions as memory, source, artifact, test, or inference. Log only meaningful decisions/corrections, not routine observations.
