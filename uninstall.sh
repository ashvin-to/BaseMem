#!/bin/bash

# BaseMem Galaxy: Uninstaller

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DATA_DIR="$HOME/.basemem"
PURGE_DATA=0
PURGE_ENV=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: ./uninstall.sh [options]

Options:
  --purge-data   Remove $DATA_DIR
  --purge-env    Remove $BASE_DIR/venv
  -y, --yes      Skip confirmation prompts
  -h, --help     Show this help
EOF
}

confirm() {
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  local prompt="$1"
  read -r -p "$prompt [y/N]: " answer
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

remove_managed_block() {
  local file="$1"
  local marker="$2"
  [ -f "$file" ] || return 0
  python3 - "$file" "$marker" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
marker = sys.argv[2]
start = f"# >>> {marker} >>>"
end = f"# <<< {marker} <<<"
text = path.read_text()
if start in text and end in text:
    prefix, rest = text.split(start, 1)
    _, suffix = rest.split(end, 1)
    new_text = (prefix.rstrip() + "\n" + suffix.lstrip()).strip()
    if new_text:
        new_text += "\n"
    path.write_text(new_text)
PY
}

remove_if_contains_marker() {
  local file="$1"
  local marker="$2"
  [ -f "$file" ] || return 0
  if grep -q "$marker" "$file"; then
    rm -f "$file"
    echo "Removed $file"
  fi
}

for arg in "$@"; do
  case "$arg" in
    --purge-data) PURGE_DATA=1 ;;
    --purge-env) PURGE_ENV=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      usage
      exit 1
      ;;
  esac
done

echo "Uninstalling BaseMem Galaxy components..."

remove_mcp_entry() {
  local file="$1"
  local key="$2"
  [ -f "$file" ] || return 0
  python3 - "$file" "$key" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
try:
    data = json.loads(path.read_text() or "{}")
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
changed = False
# Claude/Cursor/Windsurf format: mcpServers
if "mcpServers" in data and key in data["mcpServers"]:
    del data["mcpServers"][key]
    changed = True
    if not data["mcpServers"]:
        del data["mcpServers"]
# opencode format: mcp
if "mcp" in data and key in data["mcp"]:
    del data["mcp"][key]
    changed = True
    if not data["mcp"]:
        del data["mcp"]
if changed:
    if data:
        path.write_text(json.dumps(data, indent=2) + "\n")
    else:
        path.write_text("{}\n")
PY
}

for bin in "$HOME/.local/bin/mem" "/usr/local/bin/mem"; do
  [ -f "$bin" ] || continue
  if grep -q "$BASE_DIR" "$bin"; then
    if confirm "Remove $bin?"; then
      if [ -w "$bin" ]; then
        rm -f "$bin"
      else
        sudo rm -f "$bin"
      fi
      echo "Removed $bin"
    fi
  fi
done

echo "Removing MCP server entry point..."
rm -f "$BASE_DIR/mem-mcp.py"

echo "Removing MCP config entries from agent settings..."
remove_mcp_entry "$HOME/.gemini/settings.json" "basemem-memory"
remove_mcp_entry "$HOME/.gemini/config/mcp_config.json" "basemem-memory"
remove_mcp_entry "$HOME/.claude/settings.json" "basemem-memory"
remove_mcp_entry "$HOME/.config/opencode/opencode.jsonc" "basemem-memory"
remove_mcp_entry "$HOME/.cursor/mcp.json" "basemem-memory"
remove_mcp_entry "$HOME/.windsurf/mcp_config.json" "basemem-memory"

echo "Removing host guidance files..."
remove_if_contains_marker "$HOME/.codex/CODEX.md" "BaseMem"
remove_if_contains_marker "$HOME/.claude/CLAUDE.md" "BaseMem"
remove_if_contains_marker "$HOME/.config/opencode/AGENTS.md" "BaseMem"

echo "Removing Gemini extension..."
rm -rf "$HOME/.gemini/extensions/00-basemem"

echo "Removing Antigravity plugin..."
rm -rf "$HOME/.gemini/config/plugins/basemem"
rm -rf "$HOME/.gemini/antigravity/mcp/basemem-memory"

ENABLEMENT_FILE="$HOME/.gemini/extensions/extension-enablement.json"
if [ -f "$ENABLEMENT_FILE" ]; then
  python3 - "$ENABLEMENT_FILE" <<'PY'
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text() or "{}")
except json.JSONDecodeError:
    data = {}
data.pop("00-basemem", None)
if data:
    path.write_text(json.dumps(data, indent=2) + "\n")
else:
    path.write_text("{}\n")
PY
fi

remove_managed_block "$HOME/.bashrc" "BaseMem aliases"
remove_managed_block "$HOME/.zshrc" "BaseMem aliases"
remove_managed_block "$HOME/.config/fish/config.fish" "BaseMem aliases"

if [ "$PURGE_ENV" -eq 1 ] && [ -d "$BASE_DIR/venv" ]; then
  if confirm "Remove $BASE_DIR/venv?"; then
    rm -rf "$BASE_DIR/venv"
    echo "Removed $BASE_DIR/venv"
  fi
fi

if [ "$PURGE_DATA" -eq 1 ] && [ -d "$DATA_DIR" ]; then
  if confirm "Remove $DATA_DIR?"; then
    rm -rf "$DATA_DIR"
    echo "Removed $DATA_DIR"
  fi
fi

echo "------------------------------------------------"
echo "BaseMem uninstall complete."
echo "MCP configs cleaned from Claude Code, opencode, Cursor, Windsurf."
echo "Open a new shell session to refresh aliases."
echo "------------------------------------------------"
