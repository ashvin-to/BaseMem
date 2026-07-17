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
echo "Configuring MCP server entry point..."
# mem-mcp.py is now checked into the repo as a daemon proxy
chmod 755 "$BASE_DIR/mem-mcp.py"

MCP_PYTHON="$BASE_DIR/venv/bin/python3"
MCP_SCRIPT="$BASE_DIR/mem-mcp.py"
BASEMEM_DB_PATH="$DATA_DIR/basemem.db"

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

echo "Installing agent guidance files…"
BASEMEM_MCP_PYTHON="$MCP_PYTHON" \
BASEMEM_MCP_SCRIPT="$MCP_SCRIPT" \
BASEMEM_DB_PATH="$BASEMEM_DB_PATH" \
node "$BASE_DIR/bin/lib/install.js" install-all

echo "(skipped: generate_antigravity_schemas.py not present)"

echo "Configuring MCP for Gemini CLI (enterprise fallback)..."
if command -v gemini &>/dev/null; then
  gemini mcp add mem "$MCP_PYTHON" "$MCP_SCRIPT" --scope user --trust -e "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" 2>/dev/null || true
  write_json "$HOME/.gemini/settings.json" \
    "mcpServers.mem.command" "$MCP_PYTHON" \
    "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
    "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"
else
  echo "(gemini binary not found — skipped; Antigravity CLI is the consumer path)"
fi


echo "Configuring MCP for Codex CLI..."
codex mcp add --env "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" mem -- "$MCP_PYTHON" "$MCP_SCRIPT" 2>/dev/null || true
echo "Installing BaseMem skill for Codex..."
CODEX_SKILL_DIR="$HOME/.codex/skills/basemem"
mkdir -p "$CODEX_SKILL_DIR/agents"
cat <<'SKILL' >"$CODEX_SKILL_DIR/SKILL.md"
# BaseMem Rules

## Topic — always use project folder name or chat subject, never generic.

| Step | Tool | When |
|------|------|------|
| **Start** | `mem_getContext(topic, query)` | First turn, before answering |
| **During** | `mem_log_interaction(topic, decision=, fact=, ...)` | Every non-trivial decision/fact/state change |
| **End** | `mem_log_interaction(topic, summary=, activity="done")` | Session end |

Call `mem_log_interaction` at least once per session. Log decisions as they happen.

## Code — use mem_code_* instead of Read/grep/glob

| Task | Tool |
|------|------|
| Find symbol | `mem_code_find('sym')` |
| Text search | `mem_code_find('pattern', grep=True)` |
| Read file | `mem_code_read('path/file.py', offset=10, limit=50)` |
| Explore | `mem_code_explore('sym')` |
| Files | `mem_code_files(pattern='**/*.json')` |
| Trace | `mem_code_trace('func')` |
| Impact | `mem_code_impact('sym')` |

**Edit:** `code_find('sym', source=True)` → source → `edit(filePath, old, new)`

**FORBIDDEN:** `view_file`, `grep_search`, `list_dir`, `replace_file_content` — use MCP tools instead.
SKILL
cat <<'YAML' >"$CODEX_SKILL_DIR/agents/openai.yaml"
interface:
  display_name: "BaseMem Memory"
  short_description: "Persistent knowledge base with planets, notes, and code intelligence"
YAML

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

echo "Configuring MCP for Cursor..."
write_json "$HOME/.cursor/mcp.json" \
  "mcpServers.mem.command" "$MCP_PYTHON" \
  "mcpServers.mem.args" "[\"$MCP_SCRIPT\"]" \
  "mcpServers.mem.env.BASEMEM_DB_PATH" "$BASEMEM_DB_PATH"

echo "Configuring MCP for Devin..."
mkdir -p "$HOME/.config/devin"
write_json "$HOME/.config/devin/mcp_config.json" \
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
echo "  Gemini CLI      ~/.gemini/settings.json (enterprise fallback)"
echo "  Claude Code     ~/.claude/settings.json"
echo "  opencode        ~/.config/opencode/opencode.jsonc"
echo "  Cursor          ~/.cursor/mcp.json"
echo "  Devin           ~/.config/devin/mcp_config.json"
echo "  Codex CLI       ~/.codex/config.toml"
echo "  Antigravity     ~/.gemini/config/mcp_config.json"
echo ""
echo "Extensions, skills & guidance:"
echo "  Antigravity CLI  ~/.gemini/antigravity-cli/plugins/basemem/"
echo "  Antigravity IDE   ~/.gemini/antigravity/plugins/basemem/"
echo "  Codex CLI       ~/.codex/skills/basemem/"
echo "  Claude Code     ~/.claude/CLAUDE.md"
echo "  Codex CLI       ~/.codex/AGENTS.md"
echo "  opencode        ~/.config/opencode/AGENTS.md"
echo "  Gemini CLI      ~/.gemini/GEMINI.md (enterprise fallback)"
echo ""
echo "Usage:"
echo "  mem planet create my-project --goal 'Build X'"
echo "  mem agent-context --topic my-project --query 'what are we doing?'"
echo ""
echo "NOTE: You may need to restart your shell for PATH changes."
echo "------------------------------------------------"
