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

## Architecture

**Zero-RAM "Dumb Storage" Layer.** No Torch, Transformers, or FAISS. All intelligence (summaries, similarity, reranking) is provided by the connected AI agent. Memory uses ~35MB RAM.

All interfaces (CLI, MCP, Flask) read and write the same SQLite tables — no sync needed.

### Core Components

1. **Storage Layer** (`storage/`) — SQLite + FTS5, `SessionManager`, schema: planets, notes, note_links, planet_links
2. **MCP Server** (`mcp_server/server.py`) — 30 MCP tools (memory + code)
3. **Web Hub** (`server.py`) — Flask REST API, D3.js graph visualization
4. **CLI** (`cli/main.py`) — all planet, note, code commands
5. **Code Intelligence** (`indexer/`) — tree-sitter powered, per-project `.basemem.code.db`

### Removed Modules

- **Processing pipeline** — agent-driven summarization replaces `LocalSummarizer`
- **Retrieval module** — agent-driven retrieval replaces `BM25Retriever`/`VectorRetriever`
- **Orchestrator module** — agent-driven context building replaces `ContextOrchestrator`

### Project Structure

```
BaseMem/
├── cli/              # CLI commands
├── graph/            # Graph engine
├── indexer/          # Code intelligence (tree-sitter)
├── mcp_server/       # MCP server (30 tools)
├── storage/          # SQLite storage
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
│   └── code-intelligence.md
├── LICENSE
```

## Development

```bash
python -m venv venv && source venv/bin/activate && pip install -e .
pytest tests/ -v
```

## License

[MIT](./LICENSE)
