---
name: explore-codebase
description: Navigate code via symbol search and call graphs — no raw file reads
tools: [code_find, code_explore, code_read, code_files]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `code_find` | `query="symbol"`, `source=True` |
| 2 | `code_explore` | `query="symbol"` — callers, callees, source |
| 3 | `code_read` | `filePath`, `offset`, `limit` for exact ranges |

Forbidden: `view_file`, `grep_search`, `list_dir`. Tools auto-index when needed.
