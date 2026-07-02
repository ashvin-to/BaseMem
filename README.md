# BaseMem: AI Knowledge Base System

Lightweight knowledge base for AI agents. Planets hold task context, notes persist decisions, linked edges form a learnable graph. MCP tools let any agent read and write the same data. **Designed as a plugin for existing chat interfaces** (Claude Code, Codex, Gemini CLI, etc.).

## Quick Start

```bash
chmod +x setup.sh && ./setup.sh
mem planet create "my-project" --goal "Build feature X"
mem note add "my-project" --type decision -m "Use SQLite for persistence"
mem agent-context --topic "my-project" --query "what did we decide?"
```

## Docs
- **[doc/memory.md](./doc/memory.md)** — planets, notes, graphs, CLI, data models, auto-linking, memory tiers

- **[doc/code-intelligence.md](./doc/code-intelligence.md)** — tree-sitter code indexing, code tools, zero-read edit workflow

- **[doc/tasks.md](./doc/tasks.md)** — task system, CLI, MCP tools, dependency cycle prevention

## Architecture

**Zero-RAM "Dumb Storage" Layer.** No Torch, Transformers, or FAISS. All intelligence (summaries, similarity, reranking) is provided by the connected AI agent. Memory uses ~35MB RAM.

All interfaces (CLI, MCP, Flask) read and write the same SQLite tables — no sync needed.

### Core Components

1. **Storage Layer** (`storage/`) — SQLite + FTS5, `SessionManager`, schema: planets, notes, note_links, planet_links
2. **MCP Server** (`mcp_server/server.py`) — 37 MCP tools (memory + code + tasks)
3. **Web Hub** (`server.py`) — Flask REST API, D3.js graph visualization
4. **CLI** (`cli/`) — subcommands: planet, note, task, session, code, edge
5. **Code Intelligence** (`indexer/`) — tree-sitter powered, per-project `.basemem.code.db`

### Project Structure

```
BaseMem/
├── cli/              # CLI subcommands (planet, note, task, session, code, edge)
│   ├── main.py
│   ├── planet.py
│   ├── note.py
│   ├── task.py
│   ├── session.py
│   ├── code.py
│   └── edge.py
├── graph/            # Graph engine
├── indexer/          # Code intelligence (tree-sitter)
├── mcp_server/       # MCP server (37 tools)
├── storage/          # SQLite storage layer
│   ├── sessions.py   # Session manager
│   ├── planets.py    # Planet CRUD
│   ├── notes.py      # Note CRUD + linking
│   └── tasks.py      # Task CRUD
├── models.py         # Data models
├── server.py         # Flask REST API + D3 viz
├── mem.py            # CLI entry point
├── mem-mcp.py        # MCP entry point
├── setup.sh / setup.ps1
├── extensions/gemini/
├── tests/
├── README.md
├── doc/
│   ├── memory.md
│   ├── code-intelligence.md
│   └── tasks.md
├── LICENSE
```

## Development

```bash
python -m venv venv && source venv/bin/activate && pip install -e .
pytest tests/ -v
```

## License

[MIT](./LICENSE)
