#!/bin/bash

# BaseMem Galaxy: Uninstaller
# Reverses setup.sh changes while preserving user data by default.

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DATA_DIR="$HOME/.basemem"
PURGE_DATA=0
PURGE_ENV=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: ./uninstall.sh [options]

Options:
  --purge-data   Remove $DATA_DIR (sessions + database)
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
  y | Y | yes | YES) return 0 ;;
  *) return 1 ;;
  esac
}

remove_line_from_file() {
  local file="$1"
  local pattern="$2"

  [ -f "$file" ] || return 0

  local tmp
  tmp="$(mktemp)"
  awk -v pat="$pattern" 'index($0, pat) == 0 { print }' "$file" >"$tmp"
  mv "$tmp" "$file"
}

remove_if_contains_marker() {
  local file="$1"
  local marker="$2"
  [ -f "$file" ] || return 0

  if grep -q "$marker" "$file"; then
    rm -f "$file"
    echo "Removed $file"
  else
    echo "Skipped $file (content does not match BaseMem marker)"
  fi
}

for arg in "$@"; do
  case "$arg" in
  --purge-data) PURGE_DATA=1 ;;
  --purge-env) PURGE_ENV=1 ;;
  -y | --yes) ASSUME_YES=1 ;;
  -h | --help)
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

# 1. Remove global kb wrapper if it points to this installation.
for kb_path in "$HOME/.local/bin/kb" "/usr/local/bin/kb"; do
  [ -f "$kb_path" ] || continue
  if grep -q "$BASE_DIR/kb.py" "$kb_path"; then
    if confirm "Remove $kb_path?"; then
      if [ -w "$kb_path" ]; then
        rm -f "$kb_path"
      else
        sudo rm -f "$kb_path"
      fi
      echo "Removed $kb_path"
    fi
  else
    echo "Skipped $kb_path (does not point to this BaseMem install)"
  fi
done

# 3. Remove injected global protocol files when they contain BaseMem marker text.
remove_if_contains_marker "$HOME/AGENTS.md" "BaseMem Global Executive Protocol"
remove_if_contains_marker "$HOME/GEMINI.md" "BaseMem Global Executive Protocol"
remove_if_contains_marker "$HOME/.gemini/GEMINI.md" "BaseMem Global Executive Protocol"
remove_if_contains_marker "$HOME/.codex/CODEX.md" "BaseMem Global Executive Protocol"
remove_if_contains_marker "$HOME/.claude/CLAUDE.md" "BaseMem Global Executive Protocol"
remove_if_contains_marker "$BASE_DIR/AGENTS.md" "BaseMem Global Executive Protocol"

# 4. Remove installed skill and extension.
BASEMEM_EXT_DIR="$HOME/.gemini/extensions/basemem"
if [ -d "$BASEMEM_EXT_DIR" ]; then
  if confirm "Remove BaseMem extension at $BASEMEM_EXT_DIR?"; then
    rm -rf "$BASEMEM_EXT_DIR"
    echo "Removed $BASEMEM_EXT_DIR"
  fi
fi

# Cleanup old skill location if it exists
OLD_SKILL_DIR="$HOME/.gemini/extensions/superpowers/skills/basemem-memory"
if [ -d "$OLD_SKILL_DIR" ]; then
  rm -rf "$OLD_SKILL_DIR"
  echo "Cleaned up legacy skill location."
fi

# 5. Remove shell aliases added by setup.sh.
for conf in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.config/fish/config.fish"; do
  [ -f "$conf" ] || continue
  remove_line_from_file "$conf" "$BASE_DIR/ai-wrapper.sh gemini"
  remove_line_from_file "$conf" "$BASE_DIR/ai-wrapper.sh codex"
  remove_line_from_file "$conf" "$BASE_DIR/ai-wrapper.sh claude"
  echo "Updated aliases in $conf"
done

# 6. Optional: remove virtual environment created by setup.sh.
if [ "$PURGE_ENV" -eq 1 ] && [ -d "$BASE_DIR/venv" ]; then
  if confirm "Remove $BASE_DIR/venv?"; then
    rm -rf "$BASE_DIR/venv"
    echo "Removed $BASE_DIR/venv"
  fi
fi

# 7. Optional: remove BaseMem data directory.
if [ "$PURGE_DATA" -eq 1 ] && [ -d "$DATA_DIR" ]; then
  if confirm "Remove $DATA_DIR? This deletes DB and sessions."; then
    rm -rf "$DATA_DIR"
    echo "Removed $DATA_DIR"
  fi
fi

echo "------------------------------------------------"
echo "BaseMem uninstall complete."
echo "Open a new shell session to refresh aliases/commands."
echo "------------------------------------------------"
