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

## Code — use code_* tools

| Task | Tool |
|------|------|
| Find | `code_find('sym')` |
| Literal/config search | `code_find('pattern', grep=True)` |
| Read | `code_read(path, offset, limit)` |
| Explore | `code_explore('sym')` |
| Files | `code_files(pattern='**/*.json')` |

For a known target, inspect the exact file and nearby tests/callers before broad graph exploration. For unfamiliar or cross-file work, Call code_find FIRST (`code_find`). If it is empty, call `code_init(projectRoot)` once and retry; reindex after multiple symbol/signature changes or stale results.

Keep small tasks to `code_find` → `code_init` if empty/stale → exact source read → artifact inspection → focused tests, using `verify_change` for an explicit evidence bundle. Memory preserves why and durable constraints; source, artifacts, and tests establish current behavior. Memory is context, not verification. Label conclusions as memory, source, artifact, test, or inference. Log only meaningful decisions/corrections, not routine observations.
