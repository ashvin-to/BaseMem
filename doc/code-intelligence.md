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
| `code_find(query, root, dead, filePath, limit, source, references, grep)` | Find symbols. `source=True` returns lines. `references=True` finds usages. `grep=True` raw text search across ALL files |
| `code_read(filePath, offset, limit)` | Read file contents with line numbers |
| `code_explore(query, root, limit)` | One-shot: search + source code + call paths |
| `code_files(prefix, root, pattern, limit)` | List indexed files, or `pattern='**/*.json'` for glob wildcard search |
| `code_impact(symbolName, root, depth, limit)` | Transitive reverse dependency graph |
| `code_trace(symbolName, root, direction, depth, limit)` | Recursive inbound/outbound call chain |
| `code_list_projects(searchRoot)` | Scan filesystem for all indexed projects |

## CLI Commands

```
mem code init [--watch]          # Index or incrementally re-index a project
mem code sync                    # Re-index a project
mem code find <query> [--dead] [--file-path] [--source]
mem code explore <query>
mem code files [--prefix]
mem code impact <symbol> [--depth]
mem code trace <symbol> [--direction both] [--depth]
mem code query <query> [--kind] [--json]
mem code callers / callees / node / list / status / list-projects / search
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
