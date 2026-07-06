# BaseMem: Code Intelligence

Tree-sitter powered code indexing per project. Each indexed project stores a `.basemem.code.db` in its root.

## Quick Start

```bash
# Index a project (run once per project)
mem code init /path/to/project

# Watch mode: auto-re-index on file changes
mem code init --watch /path/to/project

# Find a symbol
mem code find "getContext"

# Explore: search + source + call paths in one shot
mem code explore "getContext"

# Show project file tree with symbol counts
mem code files /path/to/project

# Trace call chain
mem code trace "getContext" --direction both --depth 2

# Find impacted code (transitive reverse deps)
mem code impact "getContext" --depth 2

# List all indexed projects
mem code list-projects
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `code_init(projectRoot)` | Index a project; stores `.basemem.code.db` in project root |
| `code_find(query, projectRoot, dead, filePath, limit, source, references, grep)` | Find symbols. `source=True` returns lines. `references=True` finds usages. `grep=True` raw text search across ALL files |
| `code_read(filePath, projectRoot, offset, limit)` | Read file contents with line numbers |
| `code_explore(query, projectRoot, limit)` | One-shot: search + source code + call paths |
| `code_files(projectRoot, prefix, pattern, limit)` | List indexed files, or `pattern='**/*.json'` for glob wildcard search |
| `code_impact(symbolName, projectRoot, depth, limit)` | Transitive reverse dependency graph |
| `code_trace(symbolName, projectRoot, direction, depth, limit)` | Recursive inbound/outbound call chain |
| `code_list_projects(searchRoot)` | Scan filesystem for all indexed projects *(requires `BASEMEM_ENABLE_ADVANCED_TOOLS=1`)* |

## CLI Commands

```
mem code init [--watch]          # Index or incrementally re-index a project
mem code sync                    # Incremental re-index (changed files only)
mem code find <query> [--dead] [--file-path] [--source] [--grep]
mem code explore <query> [--limit]
mem code files [--prefix] [--pattern] [--limit]
mem code trace <symbol> [--direction] [--depth] [--limit]
mem code impact <symbol> [--depth] [--limit]
mem code list-projects           # Discover all indexed projects
mem code callers <symbol>        # Inbound callers
mem code callees <symbol>        # Outbound callees
mem code node <symbol>           # Symbol details by name or id
mem code list [--project-root]   # List all symbols in a project
mem code query <query> [--kind]  # Search symbols by name or signature
mem code search <query>          # Alias for find
mem code status                  # Index stats for a project
```

## Agent Edit Workflow

The zero-read workflow avoids Read/grep/glob for code exploration:

**Quick path (1 call):**
```
code_find('sym', source=True) → symbol location + source lines → edit(file, old, new)
```

**Full path (2 calls):**
```
code_find('sym') → symbol name/location → code_explore('sym') → view source → edit(file, old, new)
```

Run `mem code init` once per project before searching. Use `mem code list-projects` to discover indexed projects.
