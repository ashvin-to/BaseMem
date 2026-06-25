#!/bin/bash

# BaseMem Galaxy: Production Setup
# Installs mem CLI, MCP server, and agent integrations.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DATA_DIR="$HOME/.basemem"
MEM_BIN_DIR="${BASEMEM_BIN_DIR:-$HOME/.local/bin}"

echo "Initializing your Universal Knowledge Galaxy..."

mkdir -p "$DATA_DIR/sessions"

# --- Virtual environment ---
if [ ! -d "$BASE_DIR/venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$BASE_DIR/venv"
fi

echo "Installing core engine..."
"$BASE_DIR/venv/bin/pip" install -q -r "$BASE_DIR/requirements.txt"
"$BASE_DIR/venv/bin/pip" install -q -e "$BASE_DIR"

mkdir -p "$MEM_BIN_DIR"

# --- CLI wrappers ---
write_executable() {
  local target="$1"
  local content="$2"
  if [ -w "$(dirname "$target")" ]; then
    printf "%s\n" "$content" >"$target"
    chmod 755 "$target"
  else
    echo "$content" | sudo tee "$target" >/dev/null
    sudo chmod 755 "$target"
  fi
}

MEM_WRAPPER="#!/bin/bash
$BASE_DIR/venv/bin/python3 $BASE_DIR/mem.py --db $DATA_DIR/basemem.db \"\$@\""
write_executable "$MEM_BIN_DIR/mem" "$MEM_WRAPPER"

# --- MCP server entry point ---
echo "Installing MCP server entry point..."
cat <<'PYEOF' >"$BASE_DIR/mem-mcp.py"
#!/usr/bin/env python3
"""MCP server entry point for BaseMem agent memory."""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))
from mcp_server.server import server
if __name__ == "__main__":
    server.run()
PYEOF
chmod 755 "$BASE_DIR/mem-mcp.py"

MCP_PYTHON="$BASE_DIR/venv/bin/python3"
MCP_SCRIPT="$BASE_DIR/mem-mcp.py"
BASEMEM_DB_PATH="$DATA_DIR/basemem.db"

# --- Shared agent guidance (written to CODEX.md, AGENTS.md) ---
AGENT_GUIDANCE=$(cat <<'GUIDANCE'
# BaseMem Rules

## Memory flow

1. **Session start (first turn, before answering):** `mem_getContext(topic, query)`
2. **During:** `mem_log_interaction(topic, decision=, fact=, current_state=, next_step=, activity=)`
3. **Session end:** `mem_log_interaction(topic, summary=, current_state=, next_step=, activity="done")`

| Tool | When |
|------|------|
| `mem_getContext(topic, query)` | Every session start |
| `mem_log_interaction(topic, ...)` | During + end |
| `mem_read_planet(topic)` | Deep dive |
| `mem_list_planets()` | Discover topics |
| `mem_search_nodes(query)` | Full-text search |

## Code — NEVER use Read/grep/glob for code

| Task | Tool |
|------|------|
| Find symbol | `mem_code_find('sym')` |
| Find + source | `mem_code_find('sym', source=True)` |
| All references | `mem_code_find('sym', references=True)` |
| Text search (all files) | `mem_code_find('pattern', grep=True)` |
| Read file | `mem_code_read('path/file.py', offset=10, limit=50)` |
| Browse | `mem_code_find('')` |
| Explore | `mem_code_explore('sym')` |
| Files | `mem_code_files(prefix='src/')` |
| Glob files | `mem_code_files(pattern='**/*.json')` |
| Trace | `mem_code_trace('func')` |
| Impact | `mem_code_impact('sym')` |

**Edit workflow:** `code_find('sym', source=True)` → source → `edit(filePath, old, new)`
GUIDANCE
)

# --- JSON config helper (merges with existing) ---
write_json() {
  local file="$1"; shift
  python3 - "$file" "$@" <<'PY'
import json, sys
from pathlib import Path

def try_json(s):
    try: return json.loads(s)
    except (json.JSONDecodeError, TypeError): return s

path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
rest = sys.argv[2:]
i = 0
while i < len(rest):
    keys = rest[i].split(".")
    val = try_json(rest[i + 1])
    i += 2
    target = config
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    target[keys[-1]] = val
path.write_text(json.dumps(config, indent=2) + "\n")
PY
}

echo "Installing Gemini extension..."
BASEMEM_EXT_DIR="$HOME/.gemini/extensions/00-basemem"
rm -rf "$BASEMEM_EXT_DIR"
cp -r "$BASE_DIR/extensions/gemini/." "$BASEMEM_EXT_DIR"

echo "Installing Gemini AGENTS.md (global startup rules)..."
printf "%s\n" "$AGENT_GUIDANCE" >"$HOME/.gemini/config/AGENTS.md"

echo "Installing Antigravity plugin..."
ANTIGRAVITY_PLUGIN_DIR="$HOME/.gemini/config/plugins/basemem"
mkdir -p "$HOME/.gemini/config/plugins"
rm -rf "$ANTIGRAVITY_PLUGIN_DIR"
cp -r "$BASE_DIR/extensions/gemini/." "$ANTIGRAVITY_PLUGIN_DIR"
mv "$ANTIGRAVITY_PLUGIN_DIR/gemini-extension.json" "$ANTIGRAVITY_PLUGIN_DIR/plugin.json"

echo "Generating Antigravity MCP tool schemas..."
if [ -f "$BASE_DIR/generate_antigravity_schemas.py" ]; then
  python3 "$BASE_DIR/generate_antigravity_schemas.py" || true
fi

ENABLEMENT_FILE="$HOME/.gemini/extensions/extension-enablement.json"
mkdir -p "$(dirname "$ENABLEMENT_FILE")"
python3 - "$ENABLEMENT_FILE" <<'PY'
import os, json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text()) if path.exists() else {}
data["00-basemem"] = {"overrides": [os.environ.get("HOME", "~") + "/*"]}
path.write_text(json.dumps(data, indent=2) + "\n")
PY

echo "Configuring MCP for Gemini CLI..."
gemini mcp add mem "$MCP_PYTHON" "$MCP_SCRIPT" --scope user --trust -e "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" 2>/dev/null || true
write_json "$HOME/.gemini/settings.json" \
  "mcpServers.mem.command" "$MCP_PYTHON" \
  "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
  "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"

echo "Configuring MCP for Antigravity..."
write_json "$HOME/.gemini/config/mcp_config.json" \
  "mcpServers.mem.command" "$MCP_PYTHON" \
  "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
  "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"

echo "Installing host guidance files..."
mkdir -p "$HOME/.claude"
printf "%s\n" "$AGENT_GUIDANCE" >"$HOME/.claude/CLAUDE.md"

echo "Configuring MCP for Codex CLI..."
codex mcp add --env "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" mem -- "$MCP_PYTHON" "$MCP_SCRIPT" 2>/dev/null || true
echo "Installing BaseMem skill for Codex..."
CODEX_SKILL_DIR="$HOME/.codex/skills/basemem"
mkdir -p "$CODEX_SKILL_DIR/agents"
printf "%s\n" "$AGENT_GUIDANCE" >"$CODEX_SKILL_DIR/SKILL.md"
cat <<'YAML' >"$CODEX_SKILL_DIR/agents/openai.yaml"
interface:
  display_name: "BaseMem Memory"
  short_description: "Persistent knowledge base with planets, notes, and code intelligence"
YAML

echo "Installing host guidance for Codex..."
CODEX_MD_DIR="$HOME/.codex"
mkdir -p "$CODEX_MD_DIR"
printf "%s\n" "$AGENT_GUIDANCE" >"$CODEX_MD_DIR/CODEX.md"

echo "Configuring MCP for Claude Code..."
claude mcp add -s user -e "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" -- mem "$MCP_PYTHON" "$MCP_SCRIPT" 2>/dev/null || true

echo "Configuring MCP for opencode..."
mkdir -p "$HOME/.config/opencode"
write_json "$HOME/.config/opencode/opencode.jsonc" \
  "\$schema" "https://opencode.ai/config.json" \
  "mcp.mem.type" "local" \
  "mcp.mem.command" "[\"$MCP_PYTHON\",\"$MCP_SCRIPT\"]" \
  "mcp.mem.enabled" "true" \
  "mcp.mem.environment.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"
printf "%s\n" "$AGENT_GUIDANCE" >"$HOME/.config/opencode/AGENTS.md"

echo "Configuring MCP for Cursor..."
write_json "$HOME/.cursor/mcp.json" \
  "mcpServers.mem.command" "$MCP_PYTHON" \
  "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
  "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"

echo "Configuring MCP for Windsurf..."
mkdir -p "$HOME/.windsurf"
write_json "$HOME/.windsurf/mcp_config.json" \
  "mcpServers.mem.command" "$MCP_PYTHON" \
  "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
  "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"

# --- Add bin to PATH ---
SHELL_CONFIG=""
case "$(basename "${SHELL:-bash}")" in
  bash) SHELL_CONFIG="$HOME/.bashrc" ;;
  zsh) SHELL_CONFIG="$HOME/.zshrc" ;;
  fish) SHELL_CONFIG="$HOME/.config/fish/config.fish" ;;
esac
if [ -n "$SHELL_CONFIG" ] && [ -f "$SHELL_CONFIG" ]; then
  if ! grep -q "$MEM_BIN_DIR" "$SHELL_CONFIG" 2>/dev/null; then
    echo "export PATH=\"\$PATH:$MEM_BIN_DIR\"" >>"$SHELL_CONFIG"
    echo "Added $MEM_BIN_DIR to PATH in $SHELL_CONFIG"
  fi
fi

echo "------------------------------------------------"
echo "UNIVERSAL KNOWLEDGE GALAXY READY"
echo ""
echo "Installed:"
echo "  MCP server            mem (via venv)"
echo "  mem                   CLI ($MEM_BIN_DIR/mem)"
echo ""
echo "MCP configured for:"
echo "  Gemini CLI      ~/.gemini/settings.json"
echo "  Claude Code     ~/.claude/settings.json"
echo "  opencode        ~/.config/opencode/opencode.jsonc"
echo "  Cursor          ~/.cursor/mcp.json"
echo "  Windsurf        ~/.windsurf/mcp_config.json"
echo "  Codex CLI       ~/.codex/config.toml"
echo ""
echo "Extensions, skills & guidance:"
echo "  Gemini          ~/.gemini/extensions/00-basemem/"
echo "  Antigravity     ~/.gemini/config/plugins/basemem/"
echo "  Codex CLI       ~/.codex/skills/basemem/"
echo "  Claude Code     ~/.claude/CLAUDE.md"
echo "  Codex CLI       ~/.codex/CODEX.md"
echo "  opencode        ~/.config/opencode/AGENTS.md"
echo ""
echo "Usage:"
echo "  mem planet create my-project --goal 'Build X'"
echo "  mem agent-context --topic my-project --query 'what are we doing?'"
echo ""
echo "NOTE: You may need to restart your shell for PATH changes."
echo "------------------------------------------------"
