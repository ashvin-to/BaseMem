---
name: explore-codebase
description: Code exploration without reading raw files using symbol search, callers/callees, and line offsets
tools: [code_find, code_explore, code_read, code_files]
---

## Trigger
Load this skill whenever you are about to use grep, glob, view_file, list_dir, find, or cat to explore code. Those tools are FORBIDDEN in BaseMem projects. This skill shows you what to use instead.

## When to use this skill
Use this skill when navigating an unfamiliar codebase, locating symbol definitions, or planning edits without loading entire files into memory context.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `code_find(query, source=True)` | `query="symbol_name"`, `source=True` | Symbol location, signature, and source lines |
| 2 | `code_explore(query)` | `query="symbol_name"` | Callers, callees, and inline source snippet |
| 3 | Edit file directly | Target file path, exact `old_str` and `new_str` | Modified file content |

## Example

```python
# Step 1: Find symbol definition with source code
code_find("SessionManager", source=True)

# Step 2: View call relationships
code_explore("create_session")

# Step 3: Read exact range if more lines are needed
code_read(filePath="storage/sessions.py", offset=120, limit=30)
```

## Notes
FORBIDDEN tools for codebase exploration: `view_file`, `grep_search`, `list_dir`, `replace_file_content`. Always use `code_*` MCP tools instead. If `code_find` returns empty for an existing symbol, run `code_init(projectRoot)` first to index the project.
