#!/usr/bin/env python3
"""Optional capture of native agent tool use into the BaseMem knowledge base.

Called by the cross-agent PostToolUse hook (src/hooks/lib/capture.js) with a
JSON payload on stdin:

    {"tool": "Read", "params": {"file_path": "src/foo.py"}, "agent_id": "opencode"}

Automatic activity capture is **opt-in**. By default this is a no-op: every
file read/edit/search is a routine observation, not durable memory, and
auto-capturing it floods the knowledge base with low-value `activity` rows.

Enable explicitly with ``BASEMEM_CAPTURE_ACTIVITY=1`` when a project genuinely
wants an audit trail of native tool use. Even then, capture only proceeds when
the project identity can be established unambiguously; otherwise the event is
skipped rather than misattributed to whatever the current directory happens to
be named.
"""
import json
import os
import sys

# Allow running from repo root or via the MCP entry script
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mcp_server.server import get_db_path  # noqa: E402
from storage.db import StorageManager  # noqa: E402
from storage.sessions import SessionManager  # noqa: E402

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

# Generic folder / username names that make poor project identities. Mirrors
# src/hooks/lib/context.js REJECT_TOPICS so hooks and capture agree.
REJECT_TOPICS = {
    "home", "user", "users", "documents", "desktop", "downloads",
    "projects", "code", "src", "tmp", "temp", "work", "workspace", "dev",
    "repos", "github", "storage", "data", "config", "bin", "lib", "etc",
    "var", "opt", "mnt", "media",
}


def _truthy(value: "str | None") -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def capture_enabled() -> bool:
    """Automatic activity capture is opt-in (default off)."""
    return _truthy(os.environ.get("BASEMEM_CAPTURE_ACTIVITY"))


def _read_project_name(directory: str) -> "str | None":
    """Read a package.json / pyproject.toml project name from a directory."""
    pkg = os.path.join(directory, "package.json")
    try:
        if os.path.isfile(pkg):
            with open(pkg, errors="replace") as f:
                data = json.load(f)
            name = str(data.get("name") or "").strip()
            if name:
                return name
    except Exception:
        pass
    py = os.path.join(directory, "pyproject.toml")
    try:
        if os.path.isfile(py):
            import re

            with open(py, errors="replace") as f:
                for line in f:
                    m = re.match(r'^\s*name\s*=\s*"([^"]+)"', line)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return None


def _is_rejected(candidate: str) -> bool:
    lower = (candidate or "").strip().lower()
    if not lower:
        return True
    try:
        if lower == os.environ.get("USER", "").strip().lower():
            return True
    except Exception:
        pass
    return lower in REJECT_TOPICS


def _find_git_root(cwd: str) -> "str | None":
    current = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(current, ".git")) or os.path.isfile(
            os.path.join(current, ".git")
        ):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def resolve_topic() -> "str | None":
    """Resolve a reliable project identity, or None when ambiguous.

    Precedence:
      1. Explicit BASEMEM_TOPIC / BASEMEM_PLANET override.
      2. Nearest ancestor package.json / pyproject.toml project name.
      3. Basename of the enclosing verified repository (.git) root.
    Returns None when a reliable identity cannot be established, so the caller
    skips capture rather than misattributing the event.
    """
    env = (os.environ.get("BASEMEM_TOPIC") or os.environ.get("BASEMEM_PLANET") or "").strip()
    if env:
        return env

    cwd = os.environ.get("PWD") or os.getcwd()
    cwd = os.path.abspath(os.path.normpath(cwd))

    # 1. Walk up for a declared project name.
    current = cwd
    for _ in range(5):
        name = _read_project_name(current)
        if name and not _is_rejected(name):
            return name
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # 2. Fall back to the verified repository root basename.
    git_root = _find_git_root(cwd)
    if git_root:
        name = os.path.basename(git_root)
        if name and not _is_rejected(name):
            return name

    # Ambiguous: no reliable identity.
    return None


def _replace_flag(manager: SessionManager, topic: str, content: str) -> None:
    """Ensure at most one pending/missed flag note per topic.

    Deletes any existing flag note with the same content for this topic
    before inserting a fresh one, so repeated edit/write calls cannot
    stack unbounded rows.
    """
    try:
        conn = manager.storage.connection
        slug = SessionManager.normalize_topic(topic)
        rows = conn.execute(
            "SELECT id FROM notes WHERE topic = ? AND kind = 'flag' AND content = ?",
            (slug, content),
        ).fetchall()
        for row in rows:
            manager.delete_note(int(row["id"]))
    except Exception:
        pass


def _add_activity(manager: SessionManager, topic: str, content: str, agent_id: str, title: str):
    """Insert an activity note, but never treat it as a durable decision."""
    manager.add_note(
        topic,
        topic,
        "activity",
        content,
        agent_id=agent_id,
        title=title,
    )


def capture(payload: dict):
    tool = (payload.get("tool") or "").strip().lower()
    params = payload.get("params") or {}
    agent_id = payload.get("agent_id") or "system"

    # Automatic capture is opt-in and disabled by default.
    if not capture_enabled():
        return {"captured": False, "reason": "activity capture disabled"}

    # Session-boundary signal: agent ended without logging. The operational
    # record for this lives in ~/.basemem/missed-session-logs.jsonl; a durable
    # DB flag is only written when activity capture is explicitly enabled.
    if tool == "__missed_log__":
        topic = resolve_topic()
        if not topic:
            return {"captured": False, "reason": "ambiguous project identity"}
        db_path = get_db_path()
        if not os.path.isfile(db_path):
            return {"captured": False, "reason": "no db"}
        storage = StorageManager(db_path)
        manager = SessionManager(storage)
        _replace_flag(manager, topic, "missed_logInteraction")
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
    if not topic:
        # Never silently associate an event with a different project.
        return {"captured": False, "reason": "ambiguous project identity"}
    content = f"{verb} {target}" if target else verb

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return {"captured": False, "reason": "no db"}

    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    _add_activity(manager, topic, content, agent_id, f"native:{tool}")

    # Mark that an edit/write happened without a logInteraction yet.
    # One flag per topic max: stale pending flags are replaced, not stacked.
    if tool in ("edit", "write", "update_file"):
        _replace_flag(manager, topic, "pending_logInteraction")
        manager.add_note(topic, topic, "flag", "pending_logInteraction",
                         agent_id=agent_id, title="pending_logInteraction")

    return {"captured": True, "topic": topic, "content": content}


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    if not payload and len(sys.argv) > 1:
        # Also accept args form: capture_native.py '<json>'
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
