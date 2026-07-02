---
name: using-basemem
description: BaseMem memory protocol
---

## Topic — always use project folder name or chat subject, never generic.

| Step | Tool | When |
|------|------|------|
| **Start** | `getContext(topic, query)` | First turn, before answering |
| **During** | `log_interaction(topic, decision=, fact=, ...)` | Every non-trivial decision/fact/state change |
| **End** | `log_interaction(topic, summary=, activity="done")` | Session end |

Call `log_interaction` at least once per session. Log decisions as they happen.

## Code — use code_* instead of Read/grep/glob

| Task | Tool |
|------|------|
| Find symbol | `code_find('sym')` |
| Text search | `code_find('pattern', grep=True)` |
| Read file | `code_read('path/file.py', offset=10, limit=50)` |
| Explore | `code_explore('sym')` |
| Files | `code_files(pattern='**/*.json')` |
| Trace | `code_trace('func')` |
| Impact | `code_impact('sym')` |

**Edit:** `code_find('sym', source=True)` → source → `edit(filePath, old, new)`

**FORBIDDEN:** `view_file`, `grep_search`, `list_dir`, `replace_file_content` — use MCP tools instead.
