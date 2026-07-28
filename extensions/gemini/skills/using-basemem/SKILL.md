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
| Grep | `code_find('pattern', grep=True)` |
| Read | `code_read(path, offset, limit)` |
| Explore | `code_explore('sym')` |
| Files | `code_files(pattern='**/*.json')` |

Forbidden: `view_file`, `grep_search`, `list_dir`. Empty results → `code_init(root)` first.
