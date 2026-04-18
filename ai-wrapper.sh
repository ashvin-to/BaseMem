#!/bin/bash
# 🌌 UNIVERSAL AI MEMORY PROXY (Stability Fix)
TOPIC=$(basename "$PWD")
ANCHOR=$(date +%s)

# 1. RUN THE AI
"$@"

# 2. DISCOVER IDENTITY
# Any AI can integrate by setting BASEMEM_SESSION_FILE and optionally
# BASEMEM_AGENT_ID / BASEMEM_TOPIC. The fallback discovery covers common CLIs.
TOPIC="${BASEMEM_TOPIC:-$TOPIC}"
NEWEST_FILE="${BASEMEM_SESSION_FILE:-}"

if [ -z "$NEWEST_FILE" ]; then
    SEARCH_DIRS=(
        "$HOME/.gemini/tmp"
        "$HOME/.codex/sessions"
        "$HOME/.claude"
        "$HOME/.config"
        "/tmp/ai-chats"
        "/tmp"
    )
    NEWEST_FILE=$(find "${SEARCH_DIRS[@]}" \( -name "*.json" -o -name "*.jsonl" \) -newermt "@$ANCHOR" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)
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
    
    # 3. CLEAN TOPIC EXTRACTION
    # Using a simpler grep/sed combo that won't confuse the shell
    EXTRACTED_TOPIC=$(grep -oP '(-t|--topic)\s+\K(\\")?[^\\"]+(\\")?' "$NEWEST_FILE" | tail -n 1 | sed 's/\\"//g; s/\"//g')
    
    if [ ! -z "$EXTRACTED_TOPIC" ]; then
        TOPIC="$EXTRACTED_TOPIC"
        echo "🎯 BaseMem: Locked to project planet: '$TOPIC'"
    fi

    if [ -z "$AGENT_ID" ]; then
        AGENT_ID=$(basename "$1")
    fi

    echo "💾 BaseMem: Archiving Technical Moon for [$TOPIC] (Agent: $AGENT_ID)..."
    kb session sync --topic "$TOPIC" --agent-id "$AGENT_ID" --file "$NEWEST_FILE"
fi
echo "✅ Galaxy Updated."
