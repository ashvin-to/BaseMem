# Supported integrations

This matrix is generated from [`bin/lib/integrations.json`](../bin/lib/integrations.json), the same manifest consumed by the installer. It records deployment capability, not a promise that every agent exposes identical lifecycle hooks.

| Agent | Tier | Rules | MCP | Hooks/plugin | Notes |
|---|---:|:---:|:---:|:---:|---|
| Claude Code | 1 | yes | yes | hooks | native session hooks |
| Codex CLI | 1 | yes | yes | hooks | native session hooks |
| Antigravity | 1 | yes | yes | hooks | native session hooks |
| Cursor | 1 | yes | yes | hooks | native session hooks |
| Devin | 1 | yes | yes | hooks + plugin | both surfaces supported |
| Kiro | 1 | yes | yes | hooks | native session hooks |
| OpenCode | 2 | yes | yes | plugin | platform plugin |
| Cline | 2 | yes | yes | plugin | AgentPlugin format |
| Kilo Code | 2 | yes | yes | plugin | platform plugin |
| Gemini CLI | 2 | yes | yes | plugin | extension/plugin integration |
| Continue | 3 | yes | yes | — | portable configuration |
| Zed | 3 | yes | yes | — | portable configuration |
| GitHub Copilot | 3 | yes | yes | — | portable configuration |
| Aider | 3 | yes | — | — | rules only |
| VS Code | 3 | — | yes | — | MCP-only profile |
| Hermes | 3 | yes | yes | — | portable configuration |
| Mistral Vibe | 3 | yes | yes | — | portable configuration |
| Windsurf | 3 | yes | yes | — | portable configuration |

Tier 1 uses hooks to inject compact memory context at session start. Tier 2 uses a platform plugin. Tier 3 supplies portable rules and/or MCP configuration, with the agent retrieving context through the configured tool.

To inspect the live machine and effective capabilities:

```bash
node bin/lib/install.js detect
node bin/lib/install.js capabilities
```

The manifest is intentionally broad. Adding an integration does not change the core memory schema, and an integration's config path is local to that agent.
