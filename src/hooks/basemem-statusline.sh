#!/usr/bin/env bash
# Statusline indicator for Claude Code / compatible agents
set -euo pipefail

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
FLAG_FILE="${CONFIG_DIR}/.basemem-active"

RESOLVED_FLAG=$(readlink -f "$FLAG_FILE" 2>/dev/null || echo "")
RESOLVED_CONFIG=$(readlink -f "$CONFIG_DIR" 2>/dev/null || echo "")

if [ -n "$RESOLVED_FLAG" ] && [ -n "$RESOLVED_CONFIG" ]; then
  if [ "${RESOLVED_FLAG#"$RESOLVED_CONFIG"}" = "$RESOLVED_FLAG" ]; then
    exit 0
  fi
fi

if [ -f "$FLAG_FILE" ] && [ "$(cat "$FLAG_FILE" 2>/dev/null)" = "active" ]; then
  printf '[BASEMEM] [MEM]\n'
fi

exit 0
