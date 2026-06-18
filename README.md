# BaseMem: AI Knowledge Base System

A lightweight knowledge base that survives between AI sessions. Planets hold your task context, notes persist your decisions, linked edges form a learnable graph, and MCP tools let any agent read and write the same data. **Designed as a plugin for existing chat interfaces** (Claude Code, Codex, Gemini CLI, etc.) rather than a standalone chat system.

The critical integration rule:

1. After the first user prompt, read the knowledge base before the first answer.
2. Pass that retrieved context into the agent prompt or expose it as a tool.
3. Write durable updates back after the answer.

BaseMem exposes a canonical pre-answer context command:

```bash
mem agent-context --topic "project-name" --query "what am I working on?"
```

## Quick Start

### Installation (One-Command)

```bash
chmod +x setup.sh && ./setup.sh
```

This installs the `mem` CLI globally and configures MCP for Claude Code, Cursor, Windsurf, Gemini, and Codex.

### Basic Usage

```bash
# Create a planet (a topic/workspace with goals and state)
mem planet create "my-project" --goal "Build feature X" --state "Research phase"

# Update its status and next steps
mem planet set "my-project" --status active --next "Read the docs"

# Add a decision or fact
mem note add "my-project" --type decision -m "Use SQLite for persistence"

# Get agent-ready context before answering
mem agent-context --topic "my-project" --query "what did we decide?"

# Read the full planet details
mem planet read "my-project"

# Log a turn (lightweight activity record)
mem session turn --topic "my-project" --message "Reviewed the PR" --agent-id "codex"
```

### Search

```bash
mem search "what is machine learning"
```

### View your planets

```bash
mem session context
```

### Ingest AI chat history

```bash
mem session sync "topic-name" --agent-id "your-unique-suffix"
```

All CLI commands write to the same `planets` and `notes` tables that the MCP tools use — no sync needed.

## Universal Agent Integration

The agent does not automatically know your knowledge base. Your launcher and host instructions must make the agent check memory after the first user prompt and before the first answer.

### Installed CLI

Running `./setup.sh` installs `mem` and configures MCP for Claude Code, Cursor, Windsurf, Gemini, and Codex, plus hooks and plugins for automatic memory retrieval.

### MCP Tools

If your host supports MCP, the server at `src/basemem/mcp/server.py` exposes these tools:

**Context & Discovery**
- `get_agent_context(topic, query)` — compact pre-answer memory block
- `read_planet(topic)` — full planet details with all notes
- `list_planets()` — discover what topics exist
- `search_nodes(query)` — full-text search across all content
- `search_notes(topic, kind, query)` — filtered note search
- `get_node(node_id)` — read any node by ID

**Writing**
- `update_planet(topic, current_state, next_step, status, goal, ...)` — update or create a planet
- `add_note(topic, kind, content)` — persist a decision, fact, or issue
- `log_turn(topic, content)` — lightweight activity record
- `link_notes(from_id, to_id, link_type)` — connect two notes
- `link_planets(from_planet, to_planet, relation)` — connect two planets
- `set_memory_state(topic, state)` — set hot/warm/compacted

**Graph Navigation**
- `get_note_neighbors(note_id)` — find all notes linked to a note
- `get_planet_links(planet)` — find all planets linked to a planet
- `get_neighbors_weighted(note_id, depth, min_weight)` — recursive weighted traversal
- `get_subgraph(note_id, depth, min_weight)` — extract structured subgraph
- `rank_neighbors(note_id, by)` — sort neighbors by weight or confidence

**Agent-Driven Intelligence**
- `compute_similarity(note_id_a, note_id_b)` — returns both notes for agent to judge similarity
- `rerank(query, note_ids)` — returns query + notes for agent to reorder by relevance

**Code Intelligence** (tree-sitter powered, per-project `.basemem.code.db`)
- `code_init(project_root)` — index a project; stores `.basemem.code.db` in project root
- `code_search(project_root, query, limit)` — search code symbols by name or signature
- `code_node(project_root, symbol_identifier)` — get full details of a code symbol
- `code_callers(project_root, symbol_name)` — find all callers of a function
- `code_callees(project_root, symbol_name, file_path)` — find what a function calls
- `code_list(project_root, limit, offset)` — list all indexed symbols
- `code_status(project_root)` — show indexing stats
- `code_list_projects(search_root)` — scan filesystem for all indexed projects

**Graph Lifecycle**
- `edge_decay(factor, planet)` — multiply all auto-link weights by factor
- `edge_prune(threshold, planet)` — remove auto-links below weight threshold

**Lifecycle**
- `summarize_planet(topic)` — return all notes for agent summarization
- `compact_planet(topic)` — keep summaries + 30 recent notes

Recommended host policy:

1. Call `get_agent_context` after the first user prompt and before the first model answer.
2. Include that output in the working context.
3. After the answer, call `log_turn` and optionally `update_planet` or `add_note`.

## Architecture

BaseMem is a **Zero-RAM "Dumb Storage" Layer**. No Torch, Transformers, or FAISS. All intelligence (summaries, similarity, reranking) is provided by the connected AI agent. Memory uses ~35MB RAM.

### Unified Data Layer

All interfaces (CLI, MCP, Flask) read and write the same SQLite tables:

- **`planets`** — topic workspaces with state, goal, status, files, commands, next steps, memory tier (hot/warm/compacted), aliases
- **`notes`** — typed records (decision, fact, issue, question, concept, example, turn, summary) with title, agent_id, status
- **`note_links`** — weighted edges between notes with confidence, source (auto/explicit), link_type (related, depends, implements)
- **`planet_links`** — weighted edges between planets

#### Auto-Linking

When `add_note` is called, the new note is automatically linked to existing notes on the same planet using Jaccard similarity on keyword sets (threshold 0.2). Explicit links override auto links. Edge reinforcement increments auto-link weight by 0.05 on each co-access.

#### Memory Tiers

- **hot** — active working notes (default)
- **warm** — stable knowledge, not recently accessed
- **compacted** — summarized by agent, only summary + 30 recent notes preserved

### Core Components

1. **Storage Layer** (`storage/`)
   - SQLite + FTS5 for full-text search
   - `SessionManager` — all planet/note/link operations, export/import, edge lifecycle
   - Schema: planets, notes, note_links, planet_links

2. **MCP Server** (`mcp/server.py`)
   - 31 MCP tools for agent integration
   - Shares same DB path as CLI and Flask

3. **Web Hub** (`server.py`)
   - Flask REST API for all operations
   - D3.js graph visualization at `/`
   - Bookmarklet inject page at `/inject`
   - Chat logger at `/log-chat`

4. **CLI Interface** (`cli/main.py`)
   - `mem planet create/read/set/delete/compact/summarize/link/set-state`
   - `mem note add/link/neighbors`
   - `mem search` — full-text search across planets, notes, and nodes
   - `mem agent-context` — compact pre-answer memory block
   - `mem list-planets` — list all planets
   - `mem session turn/context/read/sync`
   - `mem recompute-links` — recalculate Jaccard similarity for all note pairs
   - `mem edge decay/prune` — graph lifecycle management
   - `mem export` / `mem import` — multi-device sync

5. **Code Intelligence** (`indexer/`) — per-project `.basemem.code.db` in project root
   - `mem code init [path] [--watch]` — index a project; `--watch` auto-reindexes on file changes
   - `mem code search <query> --root <path>` — search code symbols (defaults to cwd)
   - `mem code node <id|name> --root <path>` — full symbol details with callers/callees
   - `mem code callers <symbol> --root <path>` — find what calls a function
   - `mem code callees <symbol> --root <path>` — find what a function calls
   - `mem code list --root <path>` — list all indexed symbols (pagination via `--limit`/`--offset`)
   - `mem code status --root <path>` — show indexing stats
   - `mem code list-projects [--search-root]` — scan filesystem for all indexed projects
   - Run `mem code init` once per project before searching; `list-projects` discovers them

## Project Structure

```
BaseMem/
├── src/basemem/
│   ├── storage/
│   │   ├── db.py              # SQLite storage manager
│   │   └── sessions.py        # SessionManager — planets/notes/links (shared by all interfaces)
│   ├── indexer/                # Code intelligence module (tree-sitter)
│   │   ├── parser.py          # Code parser: custom queries for 5 langs, fallback for 300+ (tree-sitter)
│   │   ├── indexer.py         # Directory walker, symbol/edge persistence, FTS5 search
│   │   ├── schema.py          # code_symbols / code_edges / code_projects tables
│   │   ├── watcher.py         # Watchdog-based auto-sync on file changes
│   │   └── __init__.py
│   ├── mcp/
│   │   └── server.py          # Model Context Protocol server (31 tools)
│   ├── cli/
│   │   └── main.py            # CLI commands (same planets/notes tables)
│   ├── server.py               # Flask REST API + D3 visualization
│   ├── _entry.py               # mem entry point
│   └── __init__.py
├── graph_visualization.html    # Interactive D3 Web UI
├── bookmarklet-inject.html     # Drag-to-bookmarks memory injector
├── log-chat.html               # Drag-to-bookmarks chat logger
├── AGENTS.md                   # Universal AI Agent instructions
├── setup.sh                    # One-command install
├── uninstall.sh                # Clean removal
├── extensions/gemini/          # Gemini-specific config
├── pyproject.toml              # Project metadata
└── README.md
```

### Summary of Changes from Legacy

- **Processing pipeline removed** — LocalSummarizer, IngestWorker, ProcessingPipeline were never used in production. All summarization is agent-driven via `summarize_planet` + `add_note(topic, 'summary', ...)`.
- **Old `nodes`/`edges` tables** — retained for backward compatibility but no longer the primary model. All new data goes to `planets`/`notes`/`note_links`.
- **Retrieval, graph, orchestrator modules** — legacy code that was built for local ML processing. The system now uses agent-driven retrieval, not local BM25/vector.

## Data Models

### Planet

A topic workspace with metadata and lifecycle state.

```python
{
    "topic": "str",              # unique slug
    "display_topic": "str",      # human-readable name
    "status": "str",             # active, paused, done, archived
    "goal": "str",               # high-level objective
    "current_state": "str",      # what's happening now
    "next_step": "str",          # immediate next action
    "next_steps": "list",        # JSON array of upcoming steps
    "files": "list",             # JSON array of relevant file paths
    "commands": "list",          # JSON array of useful commands
    "handoff": "str",            # handoff notes for the next session
    "aliases": "list",           # JSON array of alternative names
    "memory_state": "str",       # hot, warm, or compacted
}
```

### Note

A typed record linked to a planet.

```python
{
    "id": "int",
    "topic": "str",              # planet slug
    "kind": "str",               # decision, fact, issue, question, concept, example, turn, summary
    "content": "str",
    "title": "str",
    "agent_id": "str",
    "status": "str",             # open, resolved, closed
    "turn_index": "int",
}
```

### Note Link

A weighted edge between two notes.

```python
{
    "from_note_id": "int",
    "to_note_id": "int",
    "link_type": "str",          # related, depends, implements, auto
    "weight": "float",           # 0-1
    "confidence": "float",       # 0-1 (auto links capped at similarity*1.5)
    "source": "str",             # auto or explicit
    "created_at": "str",
    "updated_at": "str",
}
```

### Planet Link

A weighted edge between two planets.

```python
{
    "from_planet_id": "int",
    "to_planet_id": "int",
    "relation": "str",           # related, depends
    "weight": "float",           # 0-1
}
```

## Configuration

```bash
export BASEMEM_DB_PATH="./data/basemem.db"
```

Default location: `~/.basemem/basemem.db`

## Development

### Install from source

```bash
python -m venv venv
source venv/bin/activate
pip install -e .
```

### Running Tests

```bash
pytest tests/ -v
```

## License

MIT
