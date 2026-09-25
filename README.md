# BaseMem

BaseMem is a local-first persistent project memory for coding agents. It keeps durable notes, decisions, project state, sessions, links, and code-graph evidence in SQLite so agents can recover context without making the model or a hosted service the source of truth.

**BaseMem does not replace coding-agent todos.** Keep checklists, sprint planning, and work assignment in the agent or project tool that owns delivery. BaseMem stores the durable context around that work; it is not a writable first-class task manager.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/ashvin-to/basemem/main/install.sh | bash
mem list-planets
mem log "Use SQLite with WAL mode for concurrency" --topic "my-project"
```

From a checkout:

```bash
chmod +x setup.sh && ./setup.sh
node bin/lib/install.js install-all
mem agent-context --topic "my-project"
```

The installer supports a broad set of coding agents. Run `node bin/lib/install.js capabilities` for the configured capability matrix, or `detect` to see which agents are present locally.

## What persists

- **Memory:** planets, notes, decisions, issues, tags, pins, and explicit links.
- **Project state:** current state, goals, handoffs, and next steps.
- **Sessions:** start, pause, resume, and close records so a later agent can recover the thread.
- **Code intelligence:** a local tree-sitter index with symbol search, bounded source windows, call relationships, review context, and grounded change evidence.
- **MCP and CLI:** all interfaces use the same local SQLite database; there is no synchronization service.

The connected agent performs interpretation, summarisation, and retrieval decisions. BaseMem itself does not require an embedding model, vector database, or background model server.

## Architecture

1. `storage/` owns SQLite, WAL-mode concurrency, FTS5 search, and the data model.
2. `mcp_server/` exposes memory, graph, session, and code-intelligence tools over stdio.
3. `cli/` provides the `mem` command for direct inspection and logging.
4. `indexer/` stores a per-project `.basemem.code.db` index built from source files.
5. `server.py` provides an optional local visualization/API surface.
6. `bin/lib/install.js` deploys integration rules, MCP configuration, hooks/plugins, and skills to detected agents.

The MCP executable is launched locally over stdio. BaseMem has no required network dependency after installation and does not send project memory to a hosted service.

## Retrieval and session context

Session-start hooks or plugins identify the current project, fetch a compact context, and inject it into the agent prompt. Agents with no hook/plugin support receive tiered rules that tell them how to retrieve context once. A session records the memory written during an interaction; it is a continuity record, not a task tracker.

Retrieval is deliberately grounded: use memory for durable rationale and state, then inspect current source, artifacts, and tests before making claims. The code-intelligence tools provide compact symbol context and call paths; they do not replace reading the exact source or running tests.

## Supported integration tiers

`bin/lib/integrations.json` is the machine-readable manifest. `bin/lib/install.js` derives deployment behaviour from it, and `doc/integrations.md` is the generated-readable capability matrix.

- **Tier 1:** rules, MCP, and session hooks. Best context injection.
- **Tier 2:** rules, MCP, and a native plugin. Stronger platform-native integration.
- **Tier 3:** rules and/or MCP configuration. Portable fallback for agents without reliable hooks/plugins.

The manifest includes MCP-only profiles and rules-only profiles. A profile describes a deployment capability, not a claim that every agent has identical lifecycle hooks. Integrations are deliberately broad and remain independent of the memory schema.

## Local storage, privacy, and data exit

By default, memory is stored at `~/.basemem/basemem.db` and code indexes at `.basemem.code.db` inside the indexed project. SQLite `*-wal` and `*-shm` files are transient companion files and are ignored by Git.

The optional Flask surface binds to `127.0.0.1` by default. Set `BASEMEM_CODE_WORKSPACE` to the directory containing projects you intend to expose through code APIs. Set `BASEMEM_CORS_ORIGINS` to a comma-separated allowlist only when a trusted local browser needs API access; wildcard CORS is not enabled. `BASEMEM_HOST` and `BASEMEM_PORT` configure the optional server, but changing the host can expose data and should be done deliberately.

BaseMem does not log credentials, tokens, or complete request payloads. The database remains local unless the user explicitly copies it or configures an agent/runtime that transmits it. To export data, stop the agent integrations, copy the SQLite database and any code indexes you want to retain, and use the normal filesystem transfer mechanism. To remove data, use `uninstall.sh --purge-data` or delete `~/.basemem` after backing it up. Removing integrations does not remove memory.

## Migration and legacy task workflow

The historical task table and task tools are retained in the storage compatibility layer for existing databases, but they are not advertised or deployed as a new BaseMem workflow. This preserves old data during migration without presenting tasks as the product model. Use the agent's own todo/task mechanism for current work; record durable decisions, blockers, and handoffs as memory notes.

`doc/tasks.md` is a migration archive. It documents the old schema and explains how to preserve, inspect, or remove legacy task data during an upgrade. New integrations do not install task commands or task-workflow skills. Uninstallers still remove those files from older installations.

## Commands

```text
mem log "message" --topic "project"   Record a durable decision or fact
mem planet show "project"               Read project state
mem session-start ...                   Start or resume continuity
mem session-end ...                     Close or pause continuity
mem code-init .                         Build the local code index
mem code-search "symbol" --project .    Find code symbols
mem viz                                 Start the optional local viewer
```

Use `/ctx`, `/log`, `/review`, `/mem`, and `/compact` where the agent integration provides them. Use the agent-native todo/task facility for actionable work items.

## Development and tests

```bash
bash bin/lib/test/run.sh
uv run pytest -q
```

The test suite includes installer, API, session, code-intelligence, and migration coverage. Integration support is verified against the manifest so documentation cannot drift into advertising a capability the installer does not configure.

## Documentation

- [Memory and graph](doc/memory.md)
- [Code intelligence](doc/code-intelligence.md)
- [Visualization](doc/visualization.md)
- [Supported integrations](doc/integrations.md)
- [Legacy task migration archive](doc/tasks.md)

## License

MIT. See [LICENSE](LICENSE).
