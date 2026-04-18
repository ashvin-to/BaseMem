#!/bin/bash

# 🌌 BaseMem Galaxy: Production Setup v4
# UNIVERSAL AI SUPPORT: Gemini, Codex, Claude, etc.

echo "✨ Initializing your Universal Knowledge Galaxy..."

# 1. PATH RESOLUTION
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
DATA_DIR="$HOME/.basemem"
mkdir -p "$DATA_DIR/sessions"

# 2. VIRTUAL ENVIRONMENT
if [ ! -d "$BASE_DIR/venv" ]; then
    echo "⏳ Creating virtual environment..."
    python3 -m venv "$BASE_DIR/venv"
fi

# 3. INSTALLATION
echo "⏳ Installing core engine (Zero-RAM mode)..."
"$BASE_DIR/venv/bin/pip" install -q -r "$BASE_DIR/requirements.txt"

# 4. GLOBAL CLI (kb)
echo "⏳ Linking 'kb' command to /usr/local/bin..."
WRAPPER_CONTENT="#!/bin/bash
$BASE_DIR/venv/bin/python3 $BASE_DIR/kb.py --db $DATA_DIR/basemem.db \"\$@\""
echo "$WRAPPER_CONTENT" | sudo tee /usr/local/bin/kb > /dev/null
sudo chmod +x /usr/local/bin/kb

# 5. UNIVERSAL AI PROXY (ai-wrapper.sh)
cat <<'EOF' > "$BASE_DIR/ai-wrapper.sh"
#!/bin/bash
TOPIC=$(basename "$PWD")
"$@"
TOPIC="${BASEMEM_TOPIC:-$TOPIC}"
NEWEST_FILE="${BASEMEM_SESSION_FILE:-}"
if [ -z "$NEWEST_FILE" ]; then
    SEARCH_DIRS=("$HOME/.gemini/tmp" "$HOME/.codex/sessions" "$HOME/.claude" "$HOME/.config" "/tmp/ai-chats" "/tmp")
    NEWEST_FILE=$(find "${SEARCH_DIRS[@]}" \( -name "*.json" -o -name "*.jsonl" \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)
fi
if [ ! -z "$NEWEST_FILE" ]; then
    FILE_NAME=$(basename "$NEWEST_FILE")
    if [ ! -z "$BASEMEM_AGENT_ID" ]; then
        AGENT_ID="$BASEMEM_AGENT_ID"
    elif [[ "$FILE_NAME" == rollout-*.jsonl ]]; then
        AGENT_ID=$(echo "$FILE_NAME" | grep -oP '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
    else
        AGENT_ID=$(echo "$FILE_NAME" | rev | cut -d'-' -f1 | cut -d'.' -f2 | rev)
    fi
    EXTRACTED_TOPIC=$(grep -oP 'kb session turn .*?--topic "[^"]+"' "$NEWEST_FILE" | tail -n 1 | cut -d'"' -f2)
    [ ! -z "$EXTRACTED_TOPIC" ] && TOPIC="$EXTRACTED_TOPIC"
    [ -z "$AGENT_ID" ] && AGENT_ID=$(basename "$1")
    echo "💾 BaseMem: Syncing technical Moon for [$TOPIC]..."
    kb session sync --topic "$TOPIC" --agent-id "$AGENT_ID" --file "$NEWEST_FILE"
fi
EOF
chmod +x "$BASE_DIR/ai-wrapper.sh"

# 6. UNIVERSAL INSTRUCTION INJECTION
echo "⏳ Injecting Global Protocols (Gemini, Codex, Claude)..."

PROTOCOL='# 🌌 BaseMem Global Executive Protocol
## 📥 START OF SESSION (MANDATORY)
Run these commands before anything else:
1. `activate_skill basemem-memory` (if available)
2. `kb session context` (to load project history)

## 📤 DURING SESSION
Run `kb session turn --topic "<Project>" --message "<Log>" --agent-id "<id>"` after every turn.

## 💾 END OF SESSION
Run `kb session sync --topic "<Project>" --agent-id "<id>"` before exiting.'

# Gemini
mkdir -p "$HOME/.gemini"
echo "$PROTOCOL" > "$HOME/.gemini/GEMINI.md"

# Codex
mkdir -p "$HOME/.codex"
echo "$PROTOCOL" > "$HOME/.codex/CODEX.md"

# Claude
mkdir -p "$HOME/.claude"
echo "$PROTOCOL" > "$HOME/.claude/CLAUDE.md"
# Also add to project root fallback
echo "$PROTOCOL" > "$BASE_DIR/AGENTS.md"

# 7. SKILL INSTALLATION (For Superpowers-enabled agents)
SKILL_DIR="$HOME/.gemini/extensions/superpowers/skills/basemem-memory"
mkdir -p "$SKILL_DIR"
printf "# 🌌 BaseMem 3-Tier Memory Skill\n## 📡 MISSION: Sun (Folder) -> Planet (Task) -> Moon (Archive).\n## 📥 START: Run \`kb session context\`.\n## 📤 TURN: Run \`kb session turn --topic \"<Project>\" --message \"<Log>\" --agent-id \"<id>\"\`." > "$SKILL_DIR/SKILL.md"

# 8. AUTO-SHELL ALIASING
echo "⏳ Configuring shell aliases..."
CURRENT_SHELL=$(basename "$SHELL")
CONF_FILE=""
case "$CURRENT_SHELL" in
    bash) CONF_FILE="$HOME/.bashrc" ;;
    zsh)  CONF_FILE="$HOME/.zshrc" ;;
    fish) CONF_FILE="$HOME/.config/fish/config.fish" ;;
esac

if [ ! -z "$CONF_FILE" ]; then
    for cmd in gemini codex claude; do
        if ! grep -q "alias $cmd=" "$CONF_FILE"; then
            echo "alias $cmd='$BASE_DIR/ai-wrapper.sh $cmd'" >> "$CONF_FILE"
        fi
    done
fi

echo "------------------------------------------------"
echo "✅ UNIVERSAL GALAXY READY!"
echo "🚀 Supports: Gemini, Codex, and Claude."
echo "------------------------------------------------"
