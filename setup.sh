#!/bin/bash

# BaseMem Galaxy: Production Setup v6
# Installs kb, wrapper launchers, and optional startup guidance for Gemini/Codex/Claude.

set -euo pipefail

echo "Initializing your Universal Knowledge Galaxy..."

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DATA_DIR="$HOME/.basemem"
mkdir -p "$DATA_DIR/sessions"

if [ ! -d "$BASE_DIR/venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$BASE_DIR/venv"
fi

echo "Installing core engine..."
"$BASE_DIR/venv/bin/pip" install -q -r "$BASE_DIR/requirements.txt"

MEM_BIN_DIR="${BASEMEM_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$MEM_BIN_DIR"

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

append_managed_block() {
  local file="$1"
  local marker="$2"
  local block="$3"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  python3 - "$file" "$marker" "$block" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
marker = sys.argv[2]
block = sys.argv[3]
start = f"# >>> {marker} >>>"
end = f"# <<< {marker} <<<"
text = path.read_text() if path.exists() else ""

if start in text and end in text:
    prefix, rest = text.split(start, 1)
    _, suffix = rest.split(end, 1)
    new_text = prefix.rstrip() + "\n" + start + "\n" + block.rstrip() + "\n" + end + suffix
else:
    new_text = text.rstrip()
    if new_text:
        new_text += "\n\n"
    new_text += start + "\n" + block.rstrip() + "\n" + end + "\n"

path.write_text(new_text)
PY
}

echo "Installing mem command..."
MEM_WRAPPER="#!/bin/bash
$BASE_DIR/venv/bin/python3 $BASE_DIR/mem.py --db $DATA_DIR/basemem.db \"\$@\""
write_executable "$MEM_BIN_DIR/mem" "$MEM_WRAPPER"

echo "Installing MCP server entry point..."
cat <<'PYEOF' >"$BASE_DIR/mem-mcp.py"
#!/usr/bin/env python3
"""MCP server entry point for BaseMem agent memory."""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR / "src"))
from basemem.mcp.server import server
if __name__ == "__main__":
    server.run()
PYEOF
chmod 755 "$BASE_DIR/mem-mcp.py"

echo "Installing basemem package in venv..."
"$BASE_DIR/venv/bin/pip" install -q -e "$BASE_DIR"


MCP_PYTHON="$BASE_DIR/venv/bin/python3"
MCP_SCRIPT="$BASE_DIR/mem-mcp.py"
BASEMEM_DB_PATH="$DATA_DIR/basemem.db"

echo "Installing Gemini extension..."
BASEMEM_EXT_DIR="$HOME/.gemini/extensions/00-basemem"
rm -rf "$BASEMEM_EXT_DIR"
cp -r "$BASE_DIR/extensions/gemini/." "$BASEMEM_EXT_DIR"

echo "Installing Antigravity plugin..."
ANTIGRAVITY_PLUGIN_DIR="$HOME/.gemini/config/plugins/basemem"
mkdir -p "$HOME/.gemini/config/plugins"
rm -rf "$ANTIGRAVITY_PLUGIN_DIR"
cp -r "$BASE_DIR/extensions/gemini/." "$ANTIGRAVITY_PLUGIN_DIR"
mv "$ANTIGRAVITY_PLUGIN_DIR/gemini-extension.json" "$ANTIGRAVITY_PLUGIN_DIR/plugin.json"

echo "Generating Antigravity MCP tool schemas..."
python3 "$BASE_DIR/generate_antigravity_schemas.py"

ENABLEMENT_FILE="$HOME/.gemini/extensions/extension-enablement.json"
mkdir -p "$(dirname "$ENABLEMENT_FILE")"
python3 - "$ENABLEMENT_FILE" <<'PY'
import os
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
if path.exists():
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        data = {}
else:
    data = {}
data["00-basemem"] = {"overrides": [os.environ.get("HOME", "~") + "/*"]}
path.write_text(json.dumps(data, indent=2) + "\n")
PY

echo "Configuring MCP for Gemini CLI..."
gemini mcp add basemem-memory "$MCP_PYTHON" "$MCP_SCRIPT" --scope user --trust -e "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" 2>/dev/null || true
# If already exists, update with trust
python3 - "$HOME/.gemini/settings.json" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
db_path = sys.argv[2]
if not path.exists():
    exit(0)
config = json.loads(path.read_text())
mcp = config.setdefault("mcpServers", {}).get("basemem-memory")
if mcp:
    mcp.setdefault("env", {})["BASEMEM_DB_PATH"] = db_path
    path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Configuring MCP for Antigravity (global agent config)..."
mkdir -p "$HOME/.gemini/config"
python3 - "$HOME/.gemini/config/mcp_config.json" "$MCP_PYTHON" "$MCP_SCRIPT" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
config["mcpServers"] = config.get("mcpServers", {})
config["mcpServers"]["basemem-memory"] = {
    "command": sys.argv[2],
    "args": [sys.argv[3]],
    "env": {"BASEMEM_DB_PATH": sys.argv[4]}
}
path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Installing host guidance files..."
mkdir -p "$HOME/.codex" "$HOME/.claude"
cat >"$HOME/.codex/CODEX.md" <<'CODEX'
# BaseMem Memory Protocol

<EXTREMELY-IMPORTANT>
**FAILURE MODE:** Without this protocol, every session starts from zero. You will repeat past work, forget prior decisions, and waste context on what was already resolved.

IF A MEMORY CHECK COULD BE RELEVANT TO WHAT THE USER IS ASKING, YOU DO NOT HAVE A CHOICE. YOU MUST CHECK MEMORY FIRST. This is not negotiable. This is not optional.
</EXTREMELY-IMPORTANT>

## Mandatory Startup (BEFORE answering)

BaseMem MCP tools are available. Use them in this order:

1. `list_planets` — discover what topics exist
2. `get_agent_context(topic, query="<user request>")` — ALWAYS call this before your first answer
3. Review the returned context. Prefer existing decisions. Do NOT re-ask what's already recorded.

## Mandatory Write-Back (AFTER completing work)

1. `add_note(topic, kind="decision", content="...")` for every architectural choice, fact learned, or issue found
2. `update_planet(topic, current_state="...", next_step="...")` to persist progress
3. `log_turn(topic, content="what I did")` for lightweight activity tracking

## Red Flags

If you think any of these, STOP and check memory instead:
- "I don't need to check memory yet" → Check before answering anything
- "I can check later" → Later means after starting without context
- "The topic is obvious" → You don't know what prior decisions exist
- "I already know about this" → You only know what's in this session
- "Checking memory wastes tokens" → Wasting work because you ignored prior decisions wastes more
- "The user would have told me if there was context" → Users forget; that's why memory exists
CODEX

cp "$HOME/.codex/CODEX.md" "$HOME/.claude/CLAUDE.md"

echo "Configuring MCP for Claude Code..."
mkdir -p "$HOME/.claude"
python3 - "$HOME/.claude/settings.json" "$MCP_PYTHON" "$MCP_SCRIPT" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
path = Path(sys.argv[1]) if False else None
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
config["mcpServers"] = config.get("mcpServers", {})
config["mcpServers"]["basemem-memory"] = {
    "command": sys.argv[2],
    "args": [sys.argv[3]],
    "env": {"BASEMEM_DB_PATH": sys.argv[4]}
}
path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Configuring MCP for opencode..."
mkdir -p "$HOME/.config/opencode"
python3 - "$HOME/.config/opencode/opencode.jsonc" "$MCP_PYTHON" "$MCP_SCRIPT" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {"$schema": "https://opencode.ai/config.json"}
config["mcp"] = config.get("mcp", {})
config["mcp"]["basemem-memory"] = {
    "type": "local",
    "command": [sys.argv[2], sys.argv[3]],
    "enabled": True,
    "environment": {"BASEMEM_DB_PATH": sys.argv[4]}
}
path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Installing opencode global rules..."
cat >"$HOME/.config/opencode/AGENTS.md" <<'AGENTS'
BaseMem Memory Protocol

<EXTREMELY-IMPORTANT>
**FAILURE MODE:** Without this protocol, every session starts from zero. You will repeat past work, forget prior decisions, and waste context on what was already resolved.

IF A MEMORY CHECK COULD BE RELEVANT TO WHAT THE USER IS ASKING, YOU DO NOT HAVE A CHOICE. YOU MUST CHECK MEMORY FIRST. This is not negotiable. This is not optional.
</EXTREMELY-IMPORTANT>

## Mandatory Startup (BEFORE answering)

BaseMem MCP tools are available. Use them in this order:

1. `list_planets` — discover what topics exist
2. `get_agent_context(topic, query="<user request>")` — ALWAYS call this before your first answer
3. Review the returned context. Prefer existing decisions. Do NOT re-ask what's already recorded.

## Mandatory Write-Back (AFTER completing work)

1. `add_note(topic, kind="decision", content="...")` for every architectural choice, fact learned, or issue found
2. `update_planet(topic, current_state="...", next_step="...")` to persist progress
3. `log_turn(topic, content="what I did")` for lightweight activity tracking

## Red Flags

If you think any of these, STOP and check memory instead:
- "I don't need to check memory yet" → Check before answering anything
- "I can check later" → Later means after starting without context
- "The topic is obvious" → You don't know what prior decisions exist
- "I already know about this" → You only know what's in this session
- "Checking memory wastes tokens" → Wasting work because you ignored prior decisions wastes more
- "The user would have told me if there was context" → Users forget; that's why memory exists
AGENTS

echo "Configuring MCP for Cursor..."
mkdir -p "$HOME/.cursor"
python3 - "$HOME/.cursor/mcp.json" "$MCP_PYTHON" "$MCP_SCRIPT" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
config["mcpServers"] = config.get("mcpServers", {})
config["mcpServers"]["basemem-memory"] = {
    "command": sys.argv[2],
    "args": [sys.argv[3]],
    "env": {"BASEMEM_DB_PATH": sys.argv[4]}
}
path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Configuring MCP for Windsurf..."
mkdir -p "$HOME/.windsurf"
python3 - "$HOME/.windsurf/mcp_config.json" "$MCP_PYTHON" "$MCP_SCRIPT" "$BASEMEM_DB_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
config["mcpServers"] = config.get("mcpServers", {})
config["mcpServers"]["basemem-memory"] = {
    "command": sys.argv[2],
    "args": [sys.argv[3]],
    "env": {"BASEMEM_DB_PATH": sys.argv[4]}
}
path.write_text(json.dumps(config, indent=2) + "\n")
PY

echo "Configuring shell aliases..."
CURRENT_SHELL="$(basename "${SHELL:-bash}")"
case "$CURRENT_SHELL" in
  bash) CONF_FILE="$HOME/.bashrc" ;;
  zsh) CONF_FILE="$HOME/.zshrc" ;;
  fish) CONF_FILE="$HOME/.config/fish/config.fish" ;;
  *) CONF_FILE="" ;;
esac

echo "------------------------------------------------"
echo "UNIVERSAL GALAXY READY"
echo ""
echo "Installed:"
echo "  MCP server            basemem-mcp (via venv)"
echo "  kb                    CLI for BaseMem"
echo ""
echo "MCP configured for:"
echo "  Gemini CLI      ~/.gemini/settings.json"
echo "  Claude Code     ~/.claude/settings.json"
echo "  opencode        ~/.config/opencode/opencode.jsonc"
echo "  Cursor          ~/.cursor/mcp.json"
echo "  Windsurf        ~/.windsurf/mcp_config.json"
echo ""
echo "Extensions & guidance:"
echo "  Gemini          ~/.gemini/extensions/00-basemem/ (skills/ + hooks/)"
echo "  Antigravity     ~/.gemini/config/plugins/basemem/ (plugin.json + skills/)"
echo "  Claude Code     ~/.claude/CLAUDE.md"
echo "  Codex CLI       ~/.codex/CODEX.md"
echo "  opencode        ~/.config/opencode/AGENTS.md"
echo ""
echo "Usage:"
echo "  Agents with MCP auto-discovery will connect automatically."
echo "  Gemini CLI loads BaseMem memory protocol via extension bootstrap."
echo "------------------------------------------------"
