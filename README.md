# BaseMem: AI Knowledge Base System

Lightweight, persistent memory for AI agents. Planets hold task context, notes persist decisions, linked edges form a learnable graph. **25 MCP tools** (34 with advanced) let any agent read and write the same data, and **session-start hooks/plugins** auto-inject memory context into every chat session — no manual `getContext` call needed.

## Quick Start

### Standalone (no git required)

```bash
curl -fsSL https://raw.githubusercontent.com/ashvin-to/basemem/main/install.sh | bash
```

### From repo

```bash
git clone https://github.com/ashvin-to/BaseMem.git
cd BaseMem
chmod +x setup.sh && ./setup.sh  # uses uv if available, falls back to pip
```

### Install for your agent

```bash
# Install rules + MCP config + hooks for all detected agents
node bin/lib/install.js install-all

# Or per-agent
node bin/lib/install.js install claude
node bin/lib/install.js install opencode
node bin/lib/install.js uninstall codex
```

### Verify

```bash
mem list-planets
mem planet create "my-project" --goal "Build feature X"
mem note add "my-project" --type decision -m "Use SQLite for persistence"
```

## Token Optimization

BaseMem is designed to minimize LLM context consumption:

- **Rules**: Compact shared core (~65 tokens/session) — behavioral directives only, no verbose headers
- **Skills**: Stripped to essential workflow tables — ~60% smaller than typical skill files
- **MCP server**: Shorter tool descriptions, lazy instructions (no DB query on connect)

## Slash Commands

Opencode and Antigravity get 6 slash commands installed automatically:

| Command | Purpose |
|---------|---------|
| `/ctx` | Fetch memory context for a project |
| `/log` | Log a decision or fact |
| `/review` | Review changed files with blast radius |
| `/mem` | Show project memory status |
| `/compact` | Compact old notes (keep summaries + 30 recent) |
| `/tasks` | List project tasks |

Deployed to:
- **Opencode**: `~/.config/opencode/commands/`
- **Antigravity**: `~/.gemini/antigravity-cli/skills/`

## How It Works

BaseMem installs **hooks** (for agents that support them) or **plugins** (for agent platforms with plugin systems) that fire at session/turn start. These hooks:

1. Detect the current project directory
2. Call `mem agent-context` to fetch stored memory for that project
3. Inject the context directly into the agent's prompt — no extra tool calls

If context was fetched successfully, the agent sees it as a `KNOWLEDGE_BASE_CONTEXT` block and knows not to call `getContext`. If no context exists, a fallback message tells the agent to call `getContext` once.

**Supported agents by capability:**

| Agent | Capabilities | Detected By |
|-------|-------------|-------------|
| Claude Code | rules + MCP + hooks | `~/.claude/settings.json` |
| Codex CLI | rules + MCP + hooks | `~/.codex/config.toml` |
| Antigravity (agy) | rules + MCP + hooks | `~/.gemini/.../mcp_config.json` |
| OpenCode | rules + MCP + plugin | `~/.config/opencode/opencode.jsonc` |
| Cursor | rules + MCP + hooks | `~/.cursor/mcp.json` |
| Devin | rules + MCP + hooks + plugin | `~/.config/devin/` |
| Cline | rules + MCP + plugin | `~/.cline/` |
| Kilo | rules + MCP + plugin | `~/.config/kilo/` |
| Kiro | rules + MCP + hooks | `~/.config/kiro/` |
| Gemini CLI | rules + MCP + plugin | `~/.gemini/settings.json` |
| Continue | rules + MCP | `~/.continue/config.json` |
| Zed | rules + MCP | `~/.config/zed/settings.json` |
| GitHub Copilot | rules | `copilot-instructions.md` |
| Aider | rules | `~/.aider/` (binary detection) |
| VS Code | MCP | `.vscode/mcp.json` |
| Hermes | rules + MCP | (binary detection) |

Run `node bin/lib/install.js detect` to see which are detected on your system.

## Install / Uninstall

### One-shot (all detected agents)

```bash
node bin/lib/install.js install-all     # rules + MCP + hooks for every detected agent
node bin/lib/install.js uninstall-all   # remove everything
```

### Per-agent

```bash
node bin/lib/install.js install claude
node bin/lib/install.js uninstall codex
```

### MCP only

```bash
node bin/lib/install.js install-mcp
node bin/lib/install.js install-mcp cursor
node bin/lib/install.js uninstall-mcp
```

### Standalone installer options

```bash
bash install.sh --dir ~/custom/path
bash install.sh --version v0.1.0
bash install.sh --no-gemini
```

### Uninstall

```bash
./uninstall.sh              # removes configs, hooks, MCP entries (keeps data)
./uninstall.sh --purge-data # also removes ~/.basemem/ (db + sessions)
./uninstall.sh --purge-env  # also removes venv
```

## Running Tests

```bash
pytest tests/ -v              # Python tests (MCP tools, sessions, tasks, API)
bash bin/lib/test/run.sh      # JS installer tests
```

## Docs

- **[doc/memory.md](./doc/memory.md)** — planets, notes, graphs, CLI, data models, auto-linking, memory tiers, all 25 MCP tools
- **[doc/code-intelligence.md](./doc/code-intelligence.md)** — tree-sitter code indexing, code tools, zero-read edit workflow
- **[doc/tasks.md](./doc/tasks.md)** — task system, CLI, MCP tools, dependency cycle prevention

## Architecture

**Zero-RAM "Dumb Storage" Layer.** No Torch, Transformers, or FAISS. All intelligence (summaries, similarity, reranking) is provided by the connected AI agent. Memory uses ~35MB RAM.

All interfaces (CLI, MCP, Flask) read and write the same SQLite tables — no sync needed.

### Core Components

1. **Storage Layer** (`storage/`) — SQLite + FTS5, `SessionManager`, schema: planets, notes, note_links, planet_links, sessions, tasks; config via env vars
2. **MCP Server** (`mcp_server/server.py`) — 25 core MCP tools (34 with `BASEMEM_ENABLE_ADVANCED_TOOLS=1`)
3. **Hook System** (`src/hooks/`) — session-start hook scripts shared across agents, context fetching via `mem agent-context`, conditional preamble injection
4. **Agent Plugins** (`src/agents/`) — per-agent plugin/hook definitions (opencode, cline, gemini, kilo, kiro, etc.)
5. **Web Hub** (`server.py`) — Flask REST API, D3.js graph visualization
6. **CLI** (`cli/`) — subcommands: planet, note, task, session, code, edge
7. **Code Intelligence** (`indexer/`) — tree-sitter powered, per-project `.basemem.code.db`

### Project Structure

```
BaseMem/
├── cli/              # CLI subcommands (planet, note, task, session, code, edge)
├── graph/            # Graph engine (auto-linking, traversal)
├── indexer/          # Code intelligence (tree-sitter indexing, search, trace)
├── mcp_server/       # MCP server — 25 core tools (34 with advanced)
├── storage/          # SQLite storage layer
│   ├── sessions.py   # Session manager (auto-recovery, stamping, context)
│   ├── planets.py    # Planet CRUD
│   ├── notes.py      # Note CRUD + linking
│   └── tasks.py      # Task CRUD + dependency cycle detection
├── src/
│   ├── hooks/        # Shared session-start hook scripts
│   │   ├── lib/
│   │   │   ├── context.js    # mem agent-context fetcher with topic fallback
│   │   │   └── output.js     # Format-aware hook output (claude, codex, cursor, agy)
│   │   └── basemem-session-start.js
│   └── agents/       # Per-agent hook configs + plugins
│       ├── opencode/  # OpenCode V2 plugin
│       ├── cline/     # Cline AgentPlugin
│       ├── gemini/    # Gemini extension
│       └── ...
├── bin/
│   └── lib/
│       ├── install.js    # CLI installer (rules + MCP + hooks + plugins)
│       ├── constants.js  # Agent paths, markers
│       ├── rules.js      # Rule file write/remove
│       └── settings.js   # Settings merge/clean
├── models.py         # Data models
├── server.py         # Flask REST API + D3 viz
├── mem.py            # CLI entry point
├── mem-mcp.py        # MCP entry point
├── setup.sh / setup.ps1
├── install.sh / install.ps1
├── extensions/gemini/  # Gemini CLI extension
├── tests/
├── doc/
│   ├── memory.md
│   ├── code-intelligence.md
│   └── tasks.md
└── README.md
```

## Development

```bash
python -m venv venv && source venv/bin/activate && pip install -e .
# or with uv:
uv pip install --python venv/bin/python -e .
pytest tests/ -v
```

## License

[MIT](./LICENSE)
