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

If your host supports MCP, the server at `mcp_server/server.py` exposes these tools:

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
- `code_find(query, root, dead, file_path, limit)` — find symbols by name, detail, dead code, or file filter
- `code_explore(query, root)` — one-shot: search + source code + call paths
- `code_files(prefix, root)` — project file tree with symbol counts
- `code_impact(symbol, root, depth)` — transitive reverse dependency graph
- `code_trace(symbol, root, direction, depth)` — recursive inbound/outbound call chain
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
   - 28 MCP tools (19 memory + 9 code)
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
   - `mem code init [--watch]` / `mem code sync` — index or incrementally re-index a project
   - `mem code find <query> [--dead] [--file-path]` — find symbols by name, detail, dead code, or file
   - `mem code explore <query>` — one-shot: search + source + call paths
   - `mem code files` — project file tree with symbol counts
   - `mem code impact <symbol> [--depth]` — transitive reverse dependency graph
   - `mem code trace <symbol> [--direction both] [--depth]` — recursive call chain
   - `mem code query <query> [--kind] [--json]` — raw symbol search with optional filtering
   - `mem code callers / callees / node / list / status / list-projects / search`
   - Run `mem code init` once per project before searching; `list-projects` discovers them

## Project Structure

```
BaseMem/
├── cli/
│   ├── __init__.py
│   └── main.py              # CLI commands
├── graph/
│   ├── __init__.py
│   └── engine.py            # Graph engine
├── indexer/                  # Code intelligence module (tree-sitter)
│   ├── __init__.py
│   ├── parser.py            # Code parser with tree-sitter
│   ├── indexer.py           # Directory walker, symbol/edge persistence, FTS5
│   ├── schema.py            # code tables
│   └── watcher.py           # Watchdog auto-sync
├── mcp_server/
│   ├── __init__.py
│   └── server.py            # Model Context Protocol server (28 tools)
├── processing/
│   └── __init__.py
├── storage/
│   ├── __init__.py
│   ├── db.py                # SQLite storage manager
│   └── sessions.py          # SessionManager
├── models.py                # Data models
├── server.py                # Flask REST API + D3 visualization
├── mem.py                   # CLI entry point
├── mem-mcp.py               # MCP entry point
├── pyproject.toml
├── setup.sh
├── setup.ps1
├── uninstall.sh
├── uninstall.ps1
├── extensions/gemini/
├── tests/
├── README.md
└── LICENSE
```

### Removed Modules

- **Processing pipeline** — `LocalSummarizer`, `IngestWorker`, `ProcessingPipeline`. All summarization is agent-driven via `summarize_planet` + `add_note(topic, 'summary', ...)`.
- **Retrieval module** (`retrieval/`) — `BM25Retriever`, `VectorRetriever`, `RetrievalEngine`. Agent-driven retrieval replaced local ML.
- **Orchestrator module** (`orchestrator/`) — `ContextOrchestrator` with `orchestrate()`. All context building is now agent-driven.
- **Visualization module** (`visualization/`) — `TerminalVisualizer` with ASCII graph output. Not used in production.
- **Old `nodes`/`edges` tables** — retained for backward compatibility but no longer the primary model. All new data goes to `planets`/`notes`/`note_links`.

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
