#!/bin/bash
# Universal AI memory proxy for BaseMem planets and moons.
TOPIC=$(basename "$PWD")
ANCHOR=$(date +%s)

"$@"
STATUS=$?
case "$STATUS" in
    ''|*[!0-9]*) STATUS=0 ;;
esac

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

if [ ! -f "$NEWEST_FILE" ]; then
    NEWEST_FILE=""
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
    
    EXTRACTED_TOPIC=$(grep -aoP '(kb (session turn|session sync|planet (read|set|create|compact)|note) .*?(-t|--topic)\s+|kb (planet|note)\s+)\K(\\")?[^\\"]+(\\")?' "$NEWEST_FILE" | tail -n 1 | sed 's/\\"//g; s/"//g')
    
    if [ ! -z "$EXTRACTED_TOPIC" ]; then
        TOPIC="$EXTRACTED_TOPIC"
        echo "🎯 BaseMem: Locked to project planet: '$TOPIC'"
    fi

    if [ -z "$AGENT_ID" ]; then
        AGENT_ID=$(basename "$1")
    fi

    echo "🪐 BaseMem: Compacting planet [$TOPIC]..."
    kb planet compact "$TOPIC" --agent-id "$AGENT_ID" >/dev/null 2>&1 || true
    echo "💾 BaseMem: Archiving moon for [$TOPIC] (Agent: $AGENT_ID)..."
    kb session sync --topic "$TOPIC" --agent-id "$AGENT_ID" --file "$NEWEST_FILE"
fi
echo "✅ Galaxy Updated."
exit "$STATUS"
