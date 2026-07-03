# BaseMem: AI Knowledge Base System

Lightweight knowledge base for AI agents. Planets hold task context, notes persist decisions, linked edges form a learnable graph. MCP tools let any agent read and write the same data. **Designed as a plugin for existing chat interfaces** (Claude Code, Codex, Gemini CLI, etc.).

## Quick Start

### Standalone (no git required)

```bash
curl -fsSL https://raw.githubusercontent.com/ashvin-to/basemem/main/install.sh | bash
# or: wget -qO- https://raw.githubusercontent.com/ashvin-to/basemem/main/install.sh | bash
```

### From repo

```bash
git clone https://github.com/ashvin-to/BaseMem.git
cd BaseMem
chmod +x setup.sh && ./setup.sh
```

### Verify

```bash
mem planet create "my-project" --goal "Build feature X"
mem note add "my-project" --type decision -m "Use SQLite for persistence"
mem agent-context --topic "my-project" --query "what did we decide?"
```

## Supported Agents

BaseMem writes rule files, MCP config, and hooks for 13 agents:

| Agent | Rules | MCP | Hooks | Config Path |
|-------|-------|-----|-------|-------------|
| Claude Code | `CLAUDE.md` | `mcpServers` | hooks session-start, prompt-tracker, statusline | `~/.claude.json` |
| Cursor | `.mdc` | `mcpServers` | -- | `~/.cursor/mcp.json` |
| Windsurf | `.md` | `mcpServers` | -- | `~/.windsurf/mcp_config.json` |
| VS Code | -- | `servers` key | -- | `.vscode/mcp.json` |
| GitHub Copilot | `copilot-instructions.md` | -- | -- | -- |
| Cline | `.md` | `mcpServers` | -- | `~/.cline/.../cline_mcp_settings.json` |
| Continue | `.md` | `mcpServers` | -- | `~/.continue/config.json` |
| Zed | `.md` | `mcpServers` | -- | `~/.config/zed/settings.json` |
| Codex CLI | `.md` | TOML | hooks | `~/.codex/config.toml` |
| OpenCode | `.md` | `mcp` key | plugin | `~/.config/opencode/opencode.jsonc` |
| Gemini CLI | `.md` | `mcpServers` | -- | `~/.gemini/settings.json` |
| Antigravity | `.md` | `mcpServers` | hooks | `~/.gemini/.../mcp_config.json` |
| Aider | `.md` | -- | -- | -- |

Run `node bin/lib/install.js detect` to see which are detected on your system.

## Install / Uninstall

### One-shot (all detected agents)

```bash
# Install rules + MCP + hooks for all detected agents
node bin/lib/install.js install-all

# Remove everything
node bin/lib/install.js uninstall-all
```

### Per-agent

```bash
node bin/lib/install.js install claude     # rules + hooks + MCP for Claude Code only
node bin/lib/install.js uninstall codex    # remove Codex rules + hooks + MCP
```

### MCP only

```bash
node bin/lib/install.js install-mcp        # MCP entries for all agents with MCP support
node bin/lib/install.js install-mcp cursor # MCP entry for Cursor only
node bin/lib/install.js uninstall-mcp      # Remove all MCP entries
```

### Standalone installer options

```bash
bash install.sh --dir ~/custom/path    # Install to custom directory
bash install.sh --version v0.1.0       # Install specific tag
bash install.sh --no-gemini            # Skip Gemini extension
```

## Running Tests

### Python

```bash
pytest tests/ -v
```

### JS installer

```bash
bash bin/lib/test/run.sh
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
├── install.sh / install.ps1     # Standalone installers (git/tarball)
├── extensions/gemini/
├── bin/
│   └── lib/
│       ├── constants.js         # Agent paths, markers
│       ├── rules.js             # Rule file write/remove
│       ├── settings.js          # Settings merge/clean
│       ├── install.js           # CLI installer (rules + MCP + hooks)
│       └── test/                # JS test suite
├── src/
│   ├── hooks/                   # Shared hook scripts (session-start, etc.)
│   └── agents/                  # Per-agent hook configs + plugins
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
