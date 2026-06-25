---
name: using-basemem
description: BaseMem memory protocol
---

## Memory flow

1. **Session start (before answering):** `getContext(topic, query)` — load past state
2. **During:** `log_interaction(topic, decision=, fact=, current_state=, next_step=, activity=)`
3. **Session end:** `log_interaction(topic, summary=, current_state=, next_step=, activity="done")`

| Tool | When |
|------|------|
| `getContext(topic, query)` | **Every session start** |
| `log_interaction(topic, ...)` | During + end |
| `read_planet(topic)` | Deep dive |
| `list_planets()` | Discover topics |
| `search_nodes(query)` | Full-text search |
| `search_notes(topic, kind, query)` | Filtered search |

## Code tools — NEVER use Read/grep/glob

| Task | Tool |
|------|------|
| Find symbol | `code_find('sym')` |
| Find + source | `code_find('sym', source=True)` |
| All references | `code_find('sym', references=True)` |
| Text search (all files) | `code_find('pattern', grep=True)` |
| Read file | `code_read('path/file.py', offset=10, limit=50)` |
| Browse all | `code_find('')` |
| Explore area | `code_explore('sym')` |
| Show files | `code_files(prefix='src/')` |
| Glob files | `code_files(pattern='**/*.json')` |
| Trace calls | `code_trace('func')` |
| Impact analysis | `code_impact('sym')` |

**Edit workflow:** `code_find('sym', source=True)` → source → `edit(filePath, old, new)`
**Read workflow:** `code_read('path/file.py', offset=10, limit=50)` → lines → `edit(filePath, old, new)`
