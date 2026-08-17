---
name: explore-codebase
description: "Explore repository structure, locate symbol definitions, and trace call graphs without loading large files into context. Triggers on: explore codebase, find symbol, navigate code, locate function, map repository."
---

# Codebase Exploration Protocol

Navigate codebase structure and AST symbols efficiently using indexed BaseMem queries.

## Workflow

| Step | Tool | Input | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `code_find` | `query="symbol"`, `grep=True` | Return matching filenames and line numbers (~0 tokens) |
| 2 | `code_explore` | `query="symbol"` | Discover callers, callees, and declaration signature |
| 3 | `code_read` | `path`, `offset`, `limit` (max 50 lines) | Read exact snippet containing the implementation |

## Rules

1. **Token Efficiency**: Always prefer `code_find` and `code_explore` over whole-file reads.
2. **Auto-Indexing**: BaseMem auto-indexes on first use. If results are empty, call `code_init(repo_path="...")`.
