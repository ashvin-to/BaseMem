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

KB_BIN_DIR="${BASEMEM_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$KB_BIN_DIR"

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

echo "Installing kb command..."
KB_WRAPPER="#!/bin/bash
$BASE_DIR/venv/bin/python3 $BASE_DIR/kb.py --db $DATA_DIR/basemem.db \"\$@\""
write_executable "$KB_BIN_DIR/kb" "$KB_WRAPPER"

echo "Installing wrapper launcher..."
cp "$BASE_DIR/ai-wrapper.sh" "$KB_BIN_DIR/basemem-ai"
chmod 755 "$KB_BIN_DIR/basemem-ai"

PROTOCOL_TEXT='BaseMem Startup Contract

After the first user prompt and before the first answer:
1. Determine the topic from BASEMEM_TOPIC, the current task, or the current folder.
2. Read shared memory with `kb agent-context --topic "<topic>" --query "<user request>"`.
3. Use that returned context before answering.

After answering:
1. Log durable activity with `kb session turn --topic "<topic>" --message "<short update>" --agent-id "<id>"`.
2. Store important decisions/tasks with `kb note "<topic>" --type decision|fact|task|issue --message "<durable note>" --agent-id "<id>"`.
3. Update canonical shared state with `kb planet set "<topic>" --state "<current state>" --next "<next step>"`.
4. Compact and sync transcript history when available.'

echo "Installing Codex skill payload..."
CODEX_SKILL_DIR="$HOME/.codex/skills/basemem-memory"
mkdir -p "$CODEX_SKILL_DIR"
cat <<EOF >"$CODEX_SKILL_DIR/SKILL.md"
---
name: "basemem-memory"
description: "Use when an agent should read shared BaseMem memory after the first user prompt and write durable updates back after answering."
---

# BaseMem Memory

Use this skill when an agent should read or update shared project memory across sessions or across different agents.

## Startup
- Resolve the topic from \`BASEMEM_TOPIC\`, the active task, or the current folder.
- After reading the first user prompt, run \`kb agent-context --topic "<topic>" --query "<user request>"\` before answering.
- Use the returned context as the starting memory for the session.

## Write-Back
- Log short progress with \`kb session turn --topic "<topic>" --message "<short update>" --agent-id "<id>"\`.
- Store durable notes with \`kb note "<topic>" --type decision|fact|task|issue --message "<durable note>" --agent-id "<id>"\`.
- Update canonical state with \`kb planet set "<topic>" --state "<current state>" --next "<next step>"\`.
- Run \`kb planet compact "<topic>" --agent-id "<id>"\` before transcript sync or handoff.
EOF

echo "Installing Gemini extension skill..."
BASEMEM_EXT_DIR="$HOME/.gemini/extensions/00-basemem"
mkdir -p "$BASEMEM_EXT_DIR/skills/basemem-memory"
cat <<EOF >"$BASEMEM_EXT_DIR/GEMINI.md"
# BaseMem Startup Contract

$PROTOCOL_TEXT
EOF

cat <<'EOF' >"$BASEMEM_EXT_DIR/gemini-extension.json"
{
  "name": "00-basemem",
  "description": "BaseMem startup contract and shared memory skill",
  "version": "1.1.0",
  "contextFileName": "GEMINI.md"
}
EOF

cat <<EOF >"$BASEMEM_EXT_DIR/skills/basemem-memory/SKILL.md"
# BaseMem Memory

$PROTOCOL_TEXT
EOF

ENABLEMENT_FILE="$HOME/.gemini/extensions/extension-enablement.json"
mkdir -p "$(dirname "$ENABLEMENT_FILE")"
python3 - "$ENABLEMENT_FILE" <<'PY'
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
data["00-basemem"] = {"overrides": ["/home/zoro/*"]}
path.write_text(json.dumps(data, indent=2) + "\n")
PY

mkdir -p "$HOME/.gemini/policies"
cat <<'EOF' >"$HOME/.gemini/policies/basemem.json"
{
  "name": "BaseMem Startup Contract",
  "description": "Prompt the host to use BaseMem memory before answering.",
  "priority": "MANDATORY",
  "tier": 4,
  "rules": [
    {
      "condition": "session_start",
      "action": "require_skill",
      "params": {
        "skill": "basemem-memory"
      }
    }
  ]
}
EOF

echo "Installing host guidance files..."
mkdir -p "$HOME/.codex" "$HOME/.claude"
cat <<EOF >"$HOME/.codex/CODEX.md"
# BaseMem Startup Contract

$PROTOCOL_TEXT
EOF

cat <<EOF >"$HOME/.claude/CLAUDE.md"
# BaseMem Startup Contract

$PROTOCOL_TEXT
EOF

cat <<EOF >"$HOME/GEMINI.md"
# BaseMem Startup Contract

$PROTOCOL_TEXT
EOF

echo "Configuring shell aliases..."
CURRENT_SHELL="$(basename "${SHELL:-bash}")"
case "$CURRENT_SHELL" in
  bash) CONF_FILE="$HOME/.bashrc" ;;
  zsh) CONF_FILE="$HOME/.zshrc" ;;
  fish) CONF_FILE="$HOME/.config/fish/config.fish" ;;
  *) CONF_FILE="" ;;
esac

if [ -n "${CONF_FILE}" ]; then
  if [ "$CURRENT_SHELL" = "fish" ]; then
    ALIAS_BLOCK="alias codex '$BASE_DIR/ai-wrapper.sh codex'
alias claude '$BASE_DIR/ai-wrapper.sh claude'
alias gemini '$BASE_DIR/ai-wrapper.sh gemini'"
  else
    ALIAS_BLOCK="alias codex='$BASE_DIR/ai-wrapper.sh codex'
alias claude='$BASE_DIR/ai-wrapper.sh claude'
alias gemini='$BASE_DIR/ai-wrapper.sh gemini'"
  fi
  append_managed_block "$CONF_FILE" "BaseMem aliases" "$ALIAS_BLOCK"
fi

echo "------------------------------------------------"
echo "UNIVERSAL GALAXY READY"
echo "Installed commands:"
echo "  kb"
echo "  basemem-ai"
echo
echo "Primary launch style:"
echo "  BASEMEM_TOPIC=my-topic codex"
echo "  BASEMEM_TOPIC=my-topic claude"
echo "  BASEMEM_TOPIC=my-topic gemini"
echo "------------------------------------------------"
