# BaseMem Skills System

Skills are per-workflow markdown instruction guides (`SKILL.md`) that teach AI agents how to efficiently accomplish specific tasks using BaseMem MCP tools.

## Available Skills

- `using-basemem`: Core memory protocol for tracking context, decisions, and session state.
- `code-review`: Review changed files with a single `get_review_context` call.
- `session-start`: Initialize or resume an active session on a planet.
- `explore-codebase`: Locate symbols and navigate call graphs without extraneous file reads.
- `debug-issue`: Locate error sites, check blast radius, inspect source lines, and log fixes.
- `task-workflow`: Manage task lifecycles (create, list, update, block).

## Installation

Skills are automatically installed by `bin/lib/install.js` into supported agent configuration paths:
- Claude Code: `~/.claude/skills/`
- Codex: `~/.codex/skills/`
- Agy: `~/.gemini/antigravity-cli/plugins/basemem/skills/`
- Kiro: `~/.kiro/skills/`
