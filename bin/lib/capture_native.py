#!/usr/bin/env python3
"""Silent capture of native agent tool use into the BaseMem knowledge base.

Called by the cross-agent PostToolUse hook (src/hooks/lib/capture.js) with a
JSON payload on stdin:

    {"tool": "Read", "params": {"file_path": "src/foo.py"}, "agent_id": "opencode"}

It records the action as a low-priority `activity` note on the current planet so
the memory graph stays aware of what the agent did — at zero token cost to the
agent (no round-trip, no reminder text). Native tool use is otherwise invisible
to BaseMem, so this is the safety net that keeps memory complete even when the
agent skips the MCP surface.
"""
import json
import os
import sqlite3
import sys

# Allow running from repo root or via the MCP entry script
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mcp_server.server import get_db_path
from storage.db import StorageManager
from storage.sessions import SessionManager


# Native tool -> (verb, param key holding the target path/pattern)
NATIVE_TOOLS = {
    "read": ("read", "file_path"),
    "view": ("read", "file_path"),
    "view_file": ("read", "file_path"),
    "grep": ("searched", "pattern"),
    "grep_search": ("searched", "pattern"),
    "search": ("searched", "pattern"),
    "glob": ("listed", "pattern"),
    "list_dir": ("listed", "path"),
    "edit": ("edited", "file_path"),
    "write": ("wrote", "file_path"),
    "update_file": ("edited", "file_path"),
}


def resolve_topic():
    """Prefer explicit env override, else CWD basename (mirrors plugin logic)."""
    env = os.environ.get("BASEMEM_TOPIC") or os.environ.get("BASEMEM_PLANET")
    if env:
        return env
    cwd = os.environ.get("PWD") or os.getcwd()
    return os.path.basename(os.path.normpath(cwd))


def capture(payload: dict):
    tool = (payload.get("tool") or "").strip().lower()
    params = payload.get("params") or {}
    agent_id = payload.get("agent_id") or "system"

    # Session-boundary signal: agent ended without logging.
    if tool == "__missed_log__":
        topic = resolve_topic()
        db_path = get_db_path()
        if not os.path.isfile(db_path):
            return {"captured": False, "reason": "no db"}
        storage = StorageManager(db_path)
        manager = SessionManager(storage)
        manager.add_note(topic, topic, "flag", "missed_logInteraction",
                         agent_id=agent_id, title="missed_logInteraction")
        return {"captured": True, "topic": topic, "content": "missed_logInteraction"}

    mapping = NATIVE_TOOLS.get(tool)
    if not mapping:
        return {"captured": False, "reason": "not a native tool"}

    verb, key = mapping
    target = params.get(key) or params.get("path") or params.get("file") or ""
    if isinstance(target, list):
        target = ", ".join(str(t) for t in target)
    target = str(target).strip()

    topic = resolve_topic()
    content = f"{verb} {target}" if target else verb

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return {"captured": False, "reason": "no db"}

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    manager.add_note(topic, topic, "activity", content, agent_id=agent_id,
                     title=f"native:{tool}")

    # Mark that an edit/write happened without a logInteraction yet.
    if tool in ("edit", "write", "update_file"):
        manager.add_note(topic, topic, "flag", "pending_logInteraction",
                         agent_id=agent_id, title="pending_logInteraction")

    return {"captured": True, "topic": topic, "content": content}


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        payload = {}

    if not payload:
        # Also accept args form: capture_native.py '<json>'
        if len(sys.argv) > 1:
            try:
                payload = json.loads(sys.argv[1])
            except Exception:
                payload = {}

    try:
        result = capture(payload)
    except Exception as e:
        result = {"captured": False, "error": str(e)}
    # Silent by design: only emit on stderr so it never pollutes hook stdout.
    sys.stderr.write(json.dumps(result) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
