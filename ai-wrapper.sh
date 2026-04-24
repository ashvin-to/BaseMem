#!/bin/bash
# Universal AI memory proxy for BaseMem planets and moons.
TOPIC=$(basename "$PWD")
ANCHOR=$(date +%s)
KB_CMD="kb"

if ! command -v kb >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/kb" ]; then
        KB_CMD="$HOME/.local/bin/kb"
    elif [ -x "/usr/local/bin/kb" ]; then
        KB_CMD="/usr/local/bin/kb"
    fi
fi
"$@"
STATUS=$?
case "$STATUS" in
    ''|*[!0-9]*) STATUS=0 ;;
esac
TOPIC="${BASEMEM_TOPIC:-$TOPIC}"
NEWEST_FILE="${BASEMEM_SESSION_FILE:-}"
if [ -z "$NEWEST_FILE" ]; then
    SEARCH_DIRS=("$HOME/.gemini/tmp" "$HOME/.codex/sessions" "$HOME/.claude" "$HOME/.config" "/tmp/ai-chats" "/tmp")
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
    EXTRACTED_TOPIC=$(grep -aoP '(kb (session turn|session sync|planet (read|set|create|compact)|note) .*?(-t|--topic)\s+|kb planet (read|set|create|compact)\s+|kb note\s+)\K((\\")([^\\"]+)(\\")|([^ \\"]+))' "$NEWEST_FILE" | tail -n 1 | sed 's/\\"//g; s/"//g')
    [ ! -z "$EXTRACTED_TOPIC" ] && TOPIC="$EXTRACTED_TOPIC"
    [ -z "$AGENT_ID" ] && AGENT_ID=$(basename "$1")
    echo "BaseMem: Compacting planet [$TOPIC]..."
    "$KB_CMD" planet compact "$TOPIC" --agent-id "$AGENT_ID" >/dev/null 2>&1 || true
    echo "BaseMem: Syncing moon for [$TOPIC]..."
    "$KB_CMD" session sync --topic "$TOPIC" --agent-id "$AGENT_ID" --file "$NEWEST_FILE"
fi
exit "$STATUS"
