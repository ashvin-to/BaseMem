# BaseMem SessionStart Hooks

## How It Works

When an AI agent starts a new session (or resumes one), BaseMem intercepts the startup event and injects two things:

1. **Flag file** — a `.basemem-active` sentinel written to the agent's config directory so statusline scripts and other tools can detect that BaseMem is active.
2. **Context + Rules** — the agent receives a combined block of project memory context and usage rules, either as JSON `hookSpecificOutput` or as a direct text prefix on the first user message (depending on agent architecture).

## Two-Output Format

The hook output varies by agent:

| Agent | Output Mechanism |
|-------|-----------------|
| **Claude, Codex** | Two JSON lines: (1) a `{type: "system", content}` line with the memory context, (2) a `hookSpecificOutput` line with the rules text. If no context is available, only the rules line is emitted. |
| **Cursor** | Single JSON line: `{additional_context: combined}` with both context and rules merged. |
| **Devin** | Single JSON line: `{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: combined}}`. |
| **AGy** | Reads `invocationNum` from stdin; on invocation 0 or 1 writes a `{injectSteps: [{ephemeralMessage}]}` JSON block wrapping the combined content. |
| **Kiro, OpenCode, Cline, Kilo** | Plugin-based — intercept the first chat message and inject a `<KNOWLEDGE_BASE_CONTEXT>` + `<EXTREMELY_IMPORTANT>` text prefix. No hook JSON protocol. |

The standard helper `emitHookOutput(format, contextResult, rulesText)` in `lib/output.js` handles the JSON output for all hook-protocol agents. Plugins handle their own injection.

## Topic Derivation (with `list_planets` fallback)

The shared `lib/context.js` → `fetchContext()` determines the topic in this order:

1. Walk up from `cwd` (up to 3 levels) looking for `package.json` → `name` or `pyproject.toml` → `name`.
2. If neither exists, use `path.basename(cwd)`.
3. **Rejection filter** — if the candidate matches the OS username, is in a hard-coded reject list (`home`, `user`, `documents`, `desktop`, `downloads`, etc.), or is a direct child of `$HOME` without a project file, it tries:
   - If a project file was found despite the filter: call `list-planets` and use the first non-archived planet.
   - If no project file exists: use `basename(cwd)` directly, then try `list-planets` if the reject filter still triggers.
4. Calls `mem agent-context --topic <topic>` and returns the output.

This means if the agent's working directory is a generic path (e.g. `$HOME`), it falls back to the active planet from `list-planets` rather than guessing a meaningless topic.

## Shared Library Files

All under `src/hooks/lib/`:

| File | Exports | Purpose |
|------|---------|---------|
| `context.js` | `fetchContext(options?)` | Derives topic, runs `mem agent-context`, returns `{topic, context}` or `null`. Options: `timeout` (default 3000ms), `maxDepth` (default 3). |
| `output.js` | `emitHookOutput(format, contextResult, rulesText)` | Writes the correct JSON protocol line(s) for the agent format. Formats: `claude`, `codex`, `cursor`, `devin`, `agy` (default). |
| `flagfile.js` | `writeFlagFile(configDir)` | Writes `.basemem-active` into the agent's config directory (with symlink-resolve safety check). |
| `tracker.js` | `emitTrackerOutput(format)` | Used by `UserPromptSubmit` / prompt-tracker hooks to re-remind the agent on every prompt. |

`emitHookOutput` replaces a placeholder string in the rules text (`"Memory context for this project is already injected above..."`) with either the live context or a fallback message telling the agent to call `getContext`. If the placeholder is not found (e.g., the rules were customized), the context is appended.

## How to Add Support for a New Agent

### Hook-Protocol Agent (Claude, Codex, Cursor, Devin style)

1. **Create `src/agents/<agent>/hooks/session-start.js`:**

```js
#!/usr/bin/env node
const path = require('path');
const os = require('os');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.<AGENT>_CONFIG_DIR || path.join(os.homedir(), '.<agent>');
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('<format>', contextResult, BASEMEM_RULES_TIER1);
```

2. **Create `src/agents/<agent>/hooks/prompt-tracker.js`** (optional, for per-prompt reminders):

```js
#!/usr/bin/env node
const { emitTrackerOutput } = require('../../../hooks/lib/tracker.js');
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try { JSON.parse(input); } catch (_) {}
  emitTrackerOutput('<format>');
});
```

3. **Create `src/agents/<agent>/hooks.json`** registering the hooks:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume",
      "hooks": [{
        "type": "command",
        "command": "node \"${<AGENT>_PLUGIN_ROOT}/hooks/session-start.js\"",
        "statusMessage": "Loading BaseMem memory context",
        "timeout": 10
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "node \"${<AGENT>_PLUGIN_ROOT}/hooks/prompt-tracker.js\"",
        "timeout": 5
      }]
    }]
  }
}
```

4. **Register the output format** in `lib/output.js` by adding a case to the format switch (if your agent uses a unique JSON shape).

5. **Add the agent to the installer** in `bin/lib/install.js` so `basemem install` copies the hooks and registers them.

### Plugin-Based Agent (OpenCode, Cline, Kilo, Kiro, Devin style)

These agents expose lifecycle hooks (e.g., `chat.message` or `before_agent_start`) in JavaScript/TypeScript plugin files. The pattern is:

1. Create `src/agents/<agent>/plugins/basemem.js`.
2. Find the project name via the same `package.json` / `pyproject.toml` walk.
3. Call `mem agent-context --topic <topic>` with `execSync`.
4. Inject `<KNOWLEDGE_BASE_CONTEXT>\n${context}\n</KNOWLEDGE_BASE_CONTEXT>\n\n<EXTREMELY_IMPORTANT>\n${BASEMEM_RULES}\n</EXTREMELY_IMPORTANT>` at the beginning of the first user message or system prompt.
5. Write `.basemem-active` flag file to the agent's config directory.
6. Add a per-prompt reminder (e.g. `[Memory Reminder]`) on subsequent messages.

### Statusline Integration

Create `src/agents/<agent>/` entries in the statusline hooks (`src/hooks/basemem-statusline.sh`, `src/hooks/basemem-statusline.ps1`) by adding the agent's config directory to the detection chain. The statusline scripts check for `.basemem-active` and print `[BASEMEM] [MEM]` when found.
