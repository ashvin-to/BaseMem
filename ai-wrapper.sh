#!/bin/bash
# Universal AI memory proxy for BaseMem.

set -u

TOPIC_DEFAULT=$(basename "$PWD")
KB_CMD="kb"

if ! command -v kb >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/kb" ]; then
        KB_CMD="$HOME/.local/bin/kb"
    elif [ -x "/usr/local/bin/kb" ]; then
        KB_CMD="/usr/local/bin/kb"
    fi
fi

usage() {
    cat <<'EOF'
Usage:
  ai-wrapper.sh context [topic] [query]
  ai-wrapper.sh run <agent command ...>
  ai-wrapper.sh <agent command ...>

Environment:
  BASEMEM_TOPIC         Override the topic used for context and write-back.
  BASEMEM_QUERY         Optional retrieval hint for pre-answer context.
  BASEMEM_AGENT_ID      Stable agent identifier for write-back.
  BASEMEM_SESSION_FILE  Explicit transcript file to sync after execution.
  BASEMEM_CONTEXT_FILE  Explicit path for the rendered context file.
  BASEMEM_PROMPT_FLAG   Optional prompt flag to append, e.g. --prompt or --system.
  BASEMEM_USE_STDIN=1   Pipe the KB context to stdin before the command.

Exports during run:
  BASEMEM_CONTEXT       Full pre-answer context text.
  BASEMEM_CONTEXT_FILE  File containing the same context text.

Notes:
  - This wrapper cannot guess every agent CLI's prompt flag.
  - Use `BASEMEM_PROMPT_FLAG` when the target CLI accepts a prompt string flag.
  - Use `BASEMEM_USE_STDIN=1` when the target CLI reads the prompt from stdin.
EOF
}

build_context() {
    local topic="$1"
    local query="${2:-}"
    if [ -n "$query" ]; then
        "$KB_CMD" agent-context --topic "$topic" --query "$query"
    else
        "$KB_CMD" agent-context --topic "$topic"
    fi
}

discover_session_file() {
    local anchor="$1"
    local newest_file=""
    local search_dirs=("$HOME/.gemini/tmp" "$HOME/.codex/sessions" "$HOME/.claude" "$HOME/.config" "/tmp/ai-chats" "/tmp")

    if [ -n "${BASEMEM_SESSION_FILE:-}" ] && [ -f "${BASEMEM_SESSION_FILE}" ]; then
        echo "$BASEMEM_SESSION_FILE"
        return
    fi

    newest_file=$(find "${search_dirs[@]}" \( -name "*.json" -o -name "*.jsonl" \) -newermt "@$anchor" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)
    if [ -n "$newest_file" ] && [ -f "$newest_file" ]; then
        echo "$newest_file"
    fi
}

detect_agent_id() {
    local session_file="$1"
    local default_value="$2"
    local file_name=""

    if [ -n "${BASEMEM_AGENT_ID:-}" ]; then
        echo "$BASEMEM_AGENT_ID"
        return
    fi

    if [ -n "$session_file" ]; then
        file_name=$(basename "$session_file")
        if [[ "$file_name" == rollout-*.jsonl ]]; then
            grep -oP '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<<"$file_name" | head -n 1
            return
        fi
        echo "$file_name" | rev | cut -d'-' -f1 | cut -d'.' -f2 | rev
        return
    fi

    echo "$default_value"
}

sync_after_run() {
    local topic="$1"
    local anchor="$2"
    local command_name="$3"
    local session_file agent_id extracted_topic

    session_file=$(discover_session_file "$anchor")
    if [ -z "$session_file" ]; then
        return
    fi

    agent_id=$(detect_agent_id "$session_file" "$command_name")
    extracted_topic=$(grep -aoP '(kb (session turn|session sync|planet (read|set|create|compact)|note) .*?(-t|--topic)\s+|kb planet (read|set|create|compact)\s+|kb note\s+)\K((\\")([^\\"]+)(\\")|([^ \\"]+))' "$session_file" | tail -n 1 | sed 's/\\"//g; s/"//g')
    if [ -n "$extracted_topic" ]; then
        topic="$extracted_topic"
    fi

    echo "BaseMem: Compacting topic [$topic]..." >&2
    "$KB_CMD" planet compact "$topic" --agent-id "$agent_id" >/dev/null 2>&1 || true
    echo "BaseMem: Syncing transcript for [$topic]..." >&2
    "$KB_CMD" session sync --topic "$topic" --agent-id "$agent_id" --file "$session_file" >/dev/null 2>&1 || true
}

run_agent() {
    local topic="${BASEMEM_TOPIC:-$TOPIC_DEFAULT}"
    local query="${BASEMEM_QUERY:-}"
    local anchor status context_file cmd_name
    local -a cmd

    cmd=("$@")
    cmd_name=$(basename "${cmd[0]}")
    anchor=$(date +%s)
    export BASEMEM_TOPIC="$topic"
    export BASEMEM_QUERY="$query"
    export BASEMEM_CONTEXT="$(build_context "$topic" "$query")"
    context_file="${BASEMEM_CONTEXT_FILE:-${TMPDIR:-/tmp}/basemem-context-$$.md}"
    printf '%s\n' "$BASEMEM_CONTEXT" >"$context_file"
    export BASEMEM_CONTEXT_FILE="$context_file"

    echo "BaseMem: Prepared context for topic [$topic]." >&2
    echo "BaseMem: Context file -> $BASEMEM_CONTEXT_FILE" >&2

    if [ -n "${BASEMEM_PROMPT_FLAG:-}" ]; then
        "${cmd[@]}" "$BASEMEM_PROMPT_FLAG" "$BASEMEM_CONTEXT"
        status=$?
    elif [ "${BASEMEM_USE_STDIN:-0}" = "1" ]; then
        printf '%s\n' "$BASEMEM_CONTEXT" | "${cmd[@]}"
        status=$?
    else
        echo "BaseMem: No injection mode configured; exported context via env/file only." >&2
        "${cmd[@]}"
        status=$?
    fi

    case "$status" in
        ''|*[!0-9]*) status=0 ;;
    esac

    sync_after_run "$topic" "$anchor" "$cmd_name"
    exit "$status"
}

if [ $# -eq 0 ]; then
    usage
    exit 1
fi

case "$1" in
    help|-h|--help)
        usage
        ;;
    context)
        shift
        build_context "${1:-${BASEMEM_TOPIC:-$TOPIC_DEFAULT}}" "${2:-${BASEMEM_QUERY:-}}"
        ;;
    run)
        shift
        if [ $# -eq 0 ]; then
            usage
            exit 1
        fi
        run_agent "$@"
        ;;
    *)
        run_agent "$@"
        ;;
esac
