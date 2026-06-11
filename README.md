# BaseMem: AI Knowledge Base System

A lightweight knowledge base that survives between AI sessions. Planets hold your task context, notes persist your decisions, and MCP tools let any agent read and write the same data. **Designed as a plugin for existing chat interfaces** (Claude Code, Codex, Gemini CLI, etc.) rather than a standalone chat system.

The critical integration rule is simple:

1. After the first user prompt, read the knowledge base before the first answer.
2. Pass that retrieved context into the agent prompt or expose it as a tool.
3. Write durable updates back after the answer.

BaseMem exposes a canonical pre-answer context command for that workflow:

```bash
kb agent-context --topic "project-name" --query "what am I working on?"
```

## Quick Start

### Installation (One-Command)

Simply run the setup script to make the `kb` command available globally:

```bash
chmod +x setup.sh && ./setup.sh
```

### Basic Usage

```bash
# Create a planet (a topic/workspace with goals and state)
kb planet create "my-project" --goal "Build feature X" --state "Research phase"

# Update its status and next steps
kb planet set "my-project" --status active --next "Read the docs"

# Add a decision or fact
kb note "my-project" --type decision -m "Use SQLite for persistence"

# Get agent-ready context before answering
kb agent-context --topic "my-project" --query "what did we decide?"

# Read the full planet details
kb planet read "my-project"

# Log a turn (lightweight activity record)
kb session turn --topic "my-project" --message "Reviewed the PR" --agent-id "codex"
```

### Search

```bash
kb search "what is machine learning"
```

### View your planets

```bash
kb session context
```

### Ingest AI chat history

```bash
kb session sync "topic-name" --agent-id "your-unique-suffix"
```

All CLI commands write to the same `planets` and `notes` tables that the MCP tools use — no sync needed.

## Universal Agent Integration

The agent does not automatically know your knowledge base. Your launcher and host instructions must make the agent check memory after the first user prompt and before the first answer.

### Installed CLI

Running `./setup.sh` installs `kb`:

`setup.sh` also installs MCP configurations for Claude Code, Codex, Cursor, Windsurf, and Gemini, plus hooks and plugins for automatic memory retrieval.

### MCP Tools

If your host supports MCP, the server at `src/basemem/mcp/server.py` exposes these tools:

- `get_agent_context(topic, query="")` — compact pre-answer memory block
- `read_planet(topic)` — full planet details with all notes
- `log_turn(topic, content)` — lightweight activity record
- `update_planet(topic, current_state, next_step, status, goal, ...)` — update or create a planet
- `add_note(topic, kind, content)` — persist a decision, fact, or issue
- `list_planets()` — discover what topics exist
- `search_nodes(query)` — full-text search across all content
- `search_notes(topic, kind, query)` — filtered note search
- `get_node(node_id)` — read any node by ID

Recommended host policy:

1. Call `get_agent_context` after the first user prompt and before the first model answer.
2. Include that output in the working context.
3. After the answer, call `log_turn` and optionally `update_planet` or `add_note`.

## Architecture

BaseMem has been optimized into a **Zero-RAM "Dumb Storage" Layer** by default. Heavy AI models (like Torch, Transformers, FAISS) have been stripped from the core execution path to ensure it uses ~35MB RAM. All "intelligence" (summaries, keywords) is provided by the connected AI Agent, and Semantic Gravity uses fast Keyword Overlap instead of Vector Math.

### Unified Data Layer

The CLI (`kb`) and MCP tools share the same `planets` and `notes` SQLite tables. A planet tracks a topic's state, goal, status, files, commands, and next steps. Notes record decisions, facts, issues, and activity turns. Both interfaces read and write the same data — no sync, no drift.

### Core Components

1. **Storage Layer** (`storage/`)
   - SQLite + FTS5 for full-text search
   - `planets` and `notes` tables for agent-accessible memory
   - `nodes` and `edges` tables for graph traversal
   - **Session Management**: Planet-based summaries and linked history.

2. **Retrieval Engine** (`retrieval/`)
   - BM25 for keyword matching
   - Vector search for semantic similarity
   - Hybrid merging and ranking

3. **Graph Engine** (`graph/`)
   - Node and edge management
   - Graph traversal (neighbors, paths, subgraphs)
   - **Semantic Gravity**: Automatic vector-based linking between related projects.

4. **Context Orchestrator** (`orchestrator/`)
   - Token budgeting
   - Deduplication and ranking
   - Diversity control
   - Structured context formatting

5. **Web Hub & API** (`server.py`)
   - Flask-based REST API for all commands.
   - **Obsidian Galaxy**: Dynamic D3.js visualization with Orbit mode and interactive node management.

6. **CLI Interface** (`cli/`)
   - `kb planet create/read/set/delete` — manage planets
   - `kb note` — add decisions, facts, issues
   - `kb search` — full-text search across planets, notes, and nodes
   - `kb agent-context` — compact pre-answer memory block
   - `kb list-planets` — list all planets
   - `kb session turn/context/read` — activity logging and discovery
   - `kb recompute-links` — recalculate Jaccard similarity for all note pairs
   - `kb planet set-state` — set memory tier (hot/warm/compacted)
   - `kb planet link` — link two planets
   - `kb note link` — connect two notes
   - `kb note neighbors` — show linked notes

## Data Models

### Node
```python
@dataclass
class Node:
    id: str
    title: str
    content: str
    node_type: NodeType  # concept, fact, summary, conversation, task, question, example
    keywords: List[str]
    embedding: Optional[List[float]]
    weight: float
    created_at: datetime
    last_accessed: datetime
    decay_score: float
    metadata: Dict[str, Any]
```

### Edge
```python
@dataclass
class Edge:
    from_id: str
    to_id: str
    edge_type: EdgeType  # is_a, part_of, related_to, causes, depends_on, contradicts, derived_from
    weight: float
    confidence: float
    created_at: datetime
    metadata: Dict[str, Any]
```

## Retrieval Pipeline

```
Query
  ↓
BM25 search (keyword matching) → top 50 results
  ↓
Vector search (semantic similarity) → top 50 results
  ↓
Merge and deduplicate
  ↓
Rank by: similarity × weight × decay_score
  ↓
Token-aware context packing
  ↓
Structured output formatting
```

## Project Structure

```
BaseMem/
├── src/basemem/
│   ├── models.py              # Core data classes
│   ├── storage/
│   │   ├── db.py              # SQLite storage manager (nodes/edges)
│   │   └── sessions.py        # Planet/note session logic (shared with MCP)
│   ├── retrieval/
│   │   ├── engine.py          # Hybrid retrieval
│   │   ├── bm25.py            # BM25 implementation
│   │   └── vector.py          # Vector search
│   ├── graph/
│   │   └── engine.py          # Graph operations (Semantic Gravity)
│   ├── orchestrator/
│   │   └── context.py         # Context orchestration
│   ├── mcp/
│   │   └── server.py          # Model Context Protocol server (MCP tools)
│   └── cli/
│       └── main.py            # CLI commands (same planets/notes tables)
├── tests/
│   └── test_basemem.py       # Unit tests
├── kb.py                       # Entry point
├── graph_visualization.html    # Interactive Web UI
├── AGENTS.md                  # Universal AI Agent instructions
├── requirements.txt            # Dependencies
└── pyproject.toml             # Project metadata
```

## System Evolution

### Phase 1 (Complete)
- [x] SQLite + FTS5 storage
- [x] BM25 keyword search
- [x] Hybrid retrieval (BM25 + vector)
- [x] CLI interface

### Phase 2 (Complete)
- [x] Unified planets/notes tables shared between CLI and MCP
- [x] MCP auto-config for Claude Code, opencode, Cursor, Windsurf, Gemini, Codex
- [x] Planet schema with status, goal, state, files, commands, handoff
- [x] Full-text search across planets, notes, and legacy nodes
- [x] D3.js visualization with planets panel

### Phase 3 (Planned)
- Embedding-backed similarity layer (hybrid lexical + semantic)
- Cross-encoder reranking for search
- Edge decay and pruning for adaptive graph
- Multi-device synchronization

## Configuration

```bash
export BASEMEM_DB_PATH="./data/basemem.db"
```

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Install from source

```bash
pip install -e .
```

## License

MIT
