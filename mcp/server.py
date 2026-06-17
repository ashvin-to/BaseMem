"""MCP server for BaseMem."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def get_db_path() -> str:
    """Resolve DB path and ensure schema exists."""
    path = _resolve_db_path()
    _ensure_schema()
    return path


_NOT_FOUND = object()


def _resolve_db_path() -> str:
    """Resolve DB path without side effects."""
    from_env = _env_path()
    return from_env or str(BASE_DIR / "basemem" / "basemem.db")


def _env_path() -> "str | None":
    import os

    raw = os.environ.get("BASEMEM_DB_PATH")
    if raw:
        return raw

    home = os.environ.get("HOME", "/tmp")

    # Match CLI/Flask default location
    legacy = os.path.join(home, ".basemem", "basemem.db")
    if os.path.isfile(legacy):
        return legacy

    data_dir = os.environ.get("XDG_DATA_HOME") or os.path.join(
        home, ".local", "share"
    )
    candidate = os.path.join(data_dir, "basemem", "basemem.db")
    if os.path.isfile(candidate):
        return candidate
    return None


def _get_note(topic: str, kind: str, content: str) -> "dict | None":
    """Query notes by topic, kind, and content."""
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, topic, kind, content, created_at, updated_at FROM notes WHERE topic = ? AND kind = ? AND content = ? LIMIT 1",
            (topic, kind, content),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _serialize_nodes(rows) -> "list[dict]":
    """Convert node rows to dicts."""
    return [
        {
            "id": r["id"],
            "topic": r["topic"],
            "content": r["content"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


import os
import shutil
import sqlite3

from mcp.server.fastmcp import FastMCP

server = FastMCP("basemem-mcp")

_SCHEMA_INITIALIZED = False

def _ensure_schema():
    """Create planets and notes tables if they don't exist."""
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return
    db_path = _resolve_db_path()
    if not os.path.isfile(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS planets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE NOT NULL,
                display_topic TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                goal TEXT DEFAULT '',
                current_state TEXT DEFAULT '',
                next_step TEXT DEFAULT '',
                next_steps TEXT DEFAULT '[]',
                files TEXT DEFAULT '[]',
                commands TEXT DEFAULT '[]',
                handoff TEXT DEFAULT '',
                aliases TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                title TEXT DEFAULT '',
                agent_id TEXT DEFAULT 'default',
                status TEXT DEFAULT 'open',
                turn_index INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        _SCHEMA_INITIALIZED = True
    finally:
        conn.close()

def _ensure_db_path():
    """Ensure db dir exists; called from SessionManager."""
    db_path = _resolve_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path


_REMINDER = "\n\n---\nAfter your response, call log_turn(topic=..., content=...) to persist this interaction."


@server.tool(
    description=(
        "Get the relevant agent context for a given topic. "
        "Call this first before answering any user question. "
        "Returns structured context about the topic including current state, next steps, and notes. "
        "This is the primary entry point for agent memory lookup."
    )
)
def get_agent_context(topic: str, query: str = "") -> str:
    """Retrieve agent context for a given topic from the knowledge base."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return (
            f"No knowledge base found at {db_path}. "
            f"Run `kb init` to create one."
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Auto-log this context retrieval as a turn
        try:
            conn.execute(
                "INSERT INTO notes (topic, kind, content, agent_id, turn_index) VALUES (?, 'turn', ?, 'system', 0)",
                (topic, f"Context retrieved (query: {query or 'none'})"),
            )
            conn.commit()
        except Exception:
            pass

        planet = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()

        notes = conn.execute(
            "SELECT kind, content FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 20",
            (topic,),
        ).fetchall()

        decisions = [
            n["content"]
            for n in notes
            if n["kind"] == "decision"
        ]
        issues = [
            n["content"]
            for n in notes
            if n["kind"] == "issue"
        ]
        facts = [
            n["content"]
            for n in notes
            if n["kind"] == "fact"
        ]

        parts = [f"# Context for: {topic}"]
        if planet:
            if planet["current_state"]:
                parts.append(f"\n## Current State\n{planet['current_state']}")
            if planet["next_step"]:
                parts.append(f"\n## Next Steps\n{planet['next_step']}")
        else:
            parts.append("\n*No planet found for this topic.*")

        if decisions:
            parts.append("\n## Decisions")
            parts.extend(f"- {d}" for d in decisions[-5:])
        if issues:
            parts.append("\n## Issues")
            parts.extend(f"- {i}" for i in issues[-5:])
        if facts:
            parts.append("\n## Facts")
            parts.extend(f"- {f}" for f in facts[-5:])

        return "\n".join(parts) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Read all details of a specific topic/planet, including its current state, next steps, decisions, and issues. "
        "Use this when you need the full picture of a topic, not just a summary."
    )
)
def read_planet(topic: str) -> str:
    """Read all details of a specific planet/topic."""
    import json
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        planet = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()
        if not planet:
            return f"No planet found for topic '{topic}'."

        notes = conn.execute(
            "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 50",
            (topic,),
        ).fetchall()

        display = planet["display_topic"] or planet["topic"]
        next_steps = json.loads(planet["next_steps"] or "[]")
        files = json.loads(planet["files"] or "[]")
        commands = json.loads(planet["commands"] or "[]")

        lines = [
            f"# Planet: {display}",
            f"\n**Topic slug:** {planet['topic']}",
            f"\n**Status:** {planet['status'] or 'active'}",
            f"\n**Goal:** {planet['goal'] or 'Not set'}",
            f"\n**Current State:** {planet['current_state'] or 'Not set'}",
            f"\n**Next Step:** {planet['next_step'] or 'Not set'}",
        ]
        if next_steps:
            lines.append(f"\n**All Next Steps:** {', '.join(next_steps)}")
        if files:
            lines.append(f"\n**Files:** {', '.join(files)}")
        if commands:
            lines.append(f"\n**Commands:** {', '.join(commands)}")
        if planet["handoff"]:
            lines.append(f"\n**Handoff:** {planet['handoff']}")
        if notes:
            lines.append(f"\n## Notes ({len(notes)})")
            for n in notes:
                lines.append(
                    f"\n### [{n['kind'].upper()}] (id={n['id']})\n{n['content']}\n"
                )
        return "\n".join(lines) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Log a lightweight activity record for a topic. "
        "Call this after completing a significant action or subtask. "
        "Useful for tracking what was done across sessions without adding formal notes."
    )
)
def log_turn(topic: str, content: str) -> str:
    """Log a turn/activity record for a topic."""
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO notes (topic, kind, content) VALUES (?, 'turn', ?)",
            (topic, content),
        )
        conn.commit()
        return f"Turn logged for '{topic}'."
    finally:
        conn.close()


@server.tool(
    description=(
        "Update or create a planet/topic with current state, next step, status, goal, "
        "files, commands, and handoff notes. Use this to persist progress so future "
        "sessions can pick up where you left off. Creates the planet if it doesn't exist yet."
    )
)
def update_planet(
    topic: str,
    current_state: str = "",
    next_step: str = "",
    status: str = "",
    goal: str = "",
    file_path: str = "",
    command: str = "",
    handoff: str = "",
) -> str:
    """Update or create a planet with all supported fields."""
    import sqlite3
    import json

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    conn = sqlite3.connect(db_path)
    try:
        existing = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()

        fields = {
            "current_state": current_state,
            "next_step": next_step,
            "status": status,
            "goal": goal,
            "handoff": handoff,
        }

        if existing:
            updates = []
            params = []
            for col, val in fields.items():
                if val:
                    updates.append(f"{col} = ?")
                    params.append(val)

            if file_path:
                files = set(json.loads(existing["files"] or "[]"))
                files.add(file_path)
                updates.append("files = ?")
                params.append(json.dumps(sorted(files)))

            if command:
                commands = set(json.loads(existing["commands"] or "[]"))
                commands.add(command)
                updates.append("commands = ?")
                params.append(json.dumps(sorted(commands)))

            if next_step:
                steps = set(json.loads(existing["next_steps"] or "[]"))
                steps.add(next_step)
                updates.append("next_steps = ?")
                params.append(json.dumps(sorted(steps)))

            if updates:
                params.append(topic)
                conn.execute(
                    f"UPDATE planets SET {', '.join(updates)} WHERE topic = ?",
                    params,
                )
        else:
            next_steps_set = set()
            if next_step:
                next_steps_set.add(next_step)
            files_set = set()
            if file_path:
                files_set.add(file_path)
            commands_set = set()
            if command:
                commands_set.add(command)

            conn.execute(
                "INSERT INTO planets (topic, current_state, next_step, status, goal, files, commands, handoff, next_steps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    topic,
                    current_state or "",
                    next_step or "",
                    status or "active",
                    goal or "",
                    json.dumps(sorted(files_set)),
                    json.dumps(sorted(commands_set)),
                    handoff or "",
                    json.dumps(sorted(next_steps_set)),
                ),
            )
        conn.commit()
        return f"Planet '{topic}' updated."
    finally:
        conn.close()


@server.tool(
    description=(
        "Add a note to a topic. Use kind='decision' for architectural choices, 'fact' for things you learned, "
        "'issue' for problems found, or 'turn' for lightweight activity tracking. "
        "This is how you persist knowledge across sessions."
    )
)
def add_note(topic: str, kind: str, content: str) -> str:
    """Add a note to a topic (decision, fact, issue, turn)."""
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return f"No knowledge base found at {db_path}."

    valid_kinds = {"decision", "fact", "issue", "turn", "summary"}
    if kind not in valid_kinds:
        return f"Invalid kind '{kind}'. Must be one of: {', '.join(sorted(valid_kinds))}"

    dedup = _get_note(topic, kind, content)
    if dedup:
        return f"Duplicate note skipped (already exists as id={dedup['id']})."

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO notes (topic, kind, content) VALUES (?, ?, ?)",
            (topic, kind, content),
        )
        conn.commit()
        return f"Note added to '{topic}' as a {kind}."
    finally:
        conn.close()


@server.tool(
    description=(
        "Return all raw notes for a planet, formatted for an agent to synthesize into a summary. "
        "After reading the output, call add_note(topic, 'summary', '<your summary>') to save the summary, "
        "then call compact_planet to trim old notes."
    )
)
def summarize_planet(topic: str, limit: int = 50) -> str:
    """Return all notes for a planet formatted for agent summarization."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    return manager.summarize_planet(topic, limit=limit)


@server.tool(
    description=(
        "Trim old notes from a planet, keeping only summary notes and the 30 most recent non-summary notes. "
        "Call this after summarize_planet + add_note to keep the planet manageable. "
        "Only call this when the planet has a summary note (kind='summary') to preserve context."
    )
)
def compact_planet(topic: str) -> str:
    """Compact a planet - keep summaries + 30 recent notes, delete the rest."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    count_before = manager.get_note_count(topic)
    proxy = manager.compact_planet("default", topic)
    count_after = manager.get_note_count(topic)
    return f"Compacted '{topic}': {count_before} notes -> {count_after} notes kept."


@server.tool(
    description=(
        "List all available topics/planets in the knowledge base. "
        "Use this to discover what topics exist before querying for context. "
        "Returns a list of topic names with their current state summaries."
    )
)
def list_planets() -> str:
    """List all topics/planets available in the knowledge base."""
    import sqlite3

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        planets = conn.execute(
            "SELECT topic, display_topic, status, goal, current_state FROM planets ORDER BY topic"
        ).fetchall()
        if not planets:
            return "No planets found. Create one with update_planet."
        lines = ["# Available Planets"]
        for p in planets:
            name = p["display_topic"] or p["topic"]
            state = p["current_state"] or "No state set"
            status_tag = f"[{p['status']}]" if p["status"] and p["status"] != "active" else ""
            goal = p["goal"] or ""
            goal_str = f" — {goal[:80]}" if goal else ""
            lines.append(f"- **{name}** {status_tag}: {state[:120]}{goal_str}")
        return "\n".join(lines) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Full-text search across planets, notes, and old nodes. "
        "Returns matching items with their topic, content preview, and type. "
        "Use this when you don't know which planet a piece of information belongs to."
    )
)
def search_nodes(query: str, limit: int = 10) -> str:
    """Full-text search across planets, notes, and nodes."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        like = f"%{query}%"
        lines = [f"# Search results for: '{query}'\n"]
        count = 0

        # Planets
        for r in conn.execute(
            "SELECT topic, display_topic, current_state FROM planets WHERE topic LIKE ? OR display_topic LIKE ? OR current_state LIKE ? OR goal LIKE ?",
            (like, like, like, like),
        ):
            if count >= limit:
                break
            name = r["display_topic"] or r["topic"]
            preview = (r["current_state"] or "")[:200]
            lines.append(f"🪐 **Planet: {name}**")
            if preview:
                lines.append(f"   {preview}")
            lines.append("")
            count += 1

        # Notes
        for r in conn.execute(
            "SELECT topic, kind, content FROM notes WHERE content LIKE ? OR title LIKE ?",
            (like, like),
        ):
            if count >= limit:
                break
            preview = (r["content"] or "")[:200]
            lines.append(f"[note] **{r['topic']} [{r['kind']}]**")
            lines.append(f"   {preview}")
            lines.append("")
            count += 1

        # Old nodes
        from storage.db import StorageManager
        storage = StorageManager(db_path)
        old_ids = storage.search_nodes_fts(query, limit=limit - count)
        for nid in old_ids:
            if count >= limit:
                break
            n = storage.get_node(nid)
            if n:
                preview = (n.content or "")[:200]
                lines.append(f"○ **{n.title}** ({n.node_type.value})")
                lines.append(f"   {preview}")
                lines.append("")
                count += 1
        storage.close()

        if count == 0:
            return "No matches found."

        return "\n".join(lines) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Search notes within a specific planet/topic, filtered by kind (decision/fact/issue/turn). "
        "Use this when you want to find specific types of notes within a known topic. "
        "The kind parameter filters to a specific note type."
    )
)
def search_notes(topic: str, kind: str = "", query: str = "", limit: int = 10) -> str:
    """Search notes by topic, kind, and text."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, topic, kind, content, created_at FROM notes WHERE topic = ?"
        params: list[str | int] = [topic]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        if query:
            query_lower = query.lower()
            rows = [r for r in rows if query_lower in (r["content"] or "").lower()]

        if not rows:
            return "No matching notes found."

        lines = [f"# Notes for '{topic}'" + (f" (kind: {kind})" if kind else "")]
        for r in rows:
            preview = (r["content"] or "")[:200]
            lines.append(
                f"\n**[{r['kind'].upper()}] (id={r['id']})**\n{preview}"
            )
        return "\n".join(lines) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Read any node from the knowledge base by its unique node ID. "
        "Use this after search_nodes returns results — it returns the full content of a specific node, "
        "not just a preview. Node IDs are returned by search_nodes and search_notes."
    )
)
def get_node(node_id: str) -> str:
    """Read a full node by its ID."""
    import sqlite3

    db_path = get_db_path()

    if not os.path.isfile(db_path):
        return "No knowledge base found."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, topic, content, created_at, updated_at FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            return f"No node found with id '{node_id}'."

        return (
            f"**ID:** {row['id']}\n"
            f"**Topic:** {row['topic']}\n"
            f"**Created:** {row['created_at']}\n"
            f"**Updated:** {row.get('updated_at', 'N/A')}\n"
            f"\n**Content:**\n{row['content']}"
        ) + _REMINDER
    finally:
        conn.close()


@server.tool(
    description=(
        "Create an explicit link between two notes. "
        "Note IDs are returned by add_note and search_notes (format: note-<number>). "
        "Use link_type='related' for general connections, 'depends' for dependencies."
    )
)
def link_notes(from_note_id: str, to_note_id: str, link_type: str = "related", weight: float = 1.0) -> str:
    """Link two notes together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_notes(from_note_id, to_note_id, link_type, weight)
    return msg


@server.tool(
    description=(
        "Find all notes connected to a given note via links. "
        "Returns the linked notes with their link type and weight. "
        "Note IDs are in format note-<number>."
    )
)
def get_note_neighbors(note_id: str) -> str:
    """Get neighbors of a note."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    neighbors = manager.get_note_neighbors(note_id)
    if not neighbors:
        return "No linked notes found."
    lines = [f"Neighbors of {note_id}:\n"]
    for n in neighbors:
        name = n["title"] or n["content"][:80]
        lines.append(f"- note-{n['id']} [{n['link_type']}] (w={n['weight']}) {name}")
    return "\n".join(lines) + _REMINDER


# ── Planet links ─────────────────────────────────────────────


@server.tool(
    description=(
        "Link two planets with a relation type. "
        "Planets are high-level topics/workspaces. "
        "Use relation='depends' for dependencies, 'related' for general connections."
    )
)
def link_planets(from_planet: str, to_planet: str, relation: str = "related", weight: float = 1.0) -> str:
    """Link two planets together."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.link_planets(from_planet, to_planet, relation, weight)
    return msg


@server.tool(
    description=(
        "Get all planets linked to a given planet. "
        "Returns the linked planet names, relation types, and weights."
    )
)
def get_planet_links(planet: str) -> str:
    """Get planets linked to the given planet."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    links = manager.get_planet_links(planet)
    if not links:
        return f"No planet links found for '{planet}'."
    lines = [f"Planets linked to '{planet}':\n"]
    for l in links:
        lines.append(f"- {l['planet']} [{l['relation']}] (w={l['weight']})")
    return "\n".join(lines) + _REMINDER


# ── Memory tiers ──────────────────────────────────────────────


@server.tool(
    description=(
        "Set the memory state of a planet: 'hot' (active working notes), "
        "'warm' (stable knowledge), or 'compacted' (summarized and compressed)."
    )
)
def set_memory_state(topic: str, state: str) -> str:
    """Set memory tier for a planet."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ok, msg = manager.set_memory_state(topic, state)
    return msg


# ── Graph-aware retrieval ─────────────────────────────────────


@server.tool(
    description=(
        "Get neighbors of a note up to a given depth. "
        "Performs weighted traversal returning all connected notes. "
        "Use depth=1 for direct neighbors, depth=2 for neighbors-of-neighbors. "
        "min_weight filters by minimum edge weight."
    )
)
def get_neighbors_weighted(note_id: str, depth: int = 1, min_weight: float = 0.0) -> str:
    """Weighted neighbor traversal with configurable depth."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    results = manager.get_neighbors_weighted(nid, depth=depth, min_weight=min_weight)
    if not results:
        return "No neighbors found at this depth."
    lines = [f"Neighbors (depth={depth}, min_weight={min_weight}):\n"]
    for r in results:
        lines.append(f"  note-{r['id']} [{r['link_type']}] (w={r['weight']}, d={r['_depth']}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines) + _REMINDER


@server.tool(
    description=(
        "Extract a weighted subgraph around a note. "
        "Returns structured JSON with nodes and edges for LLM summarization. "
        "Use depth=2 for k-hop exploration, min_weight=0.2 to filter weak links."
    )
)
def get_subgraph(note_id: str, depth: int = 2, min_weight: float = 0.2) -> str:
    """Extract weighted subgraph around a note."""
    import json
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    result = manager.get_subgraph(nid, depth=depth, min_weight=min_weight)
    return json.dumps(result, indent=2) + _REMINDER


@server.tool(
    description=(
        "Rank neighbors of a note by weight or confidence. "
        "Returns neighbors sorted descending by the selected metric."
    )
)
def rank_neighbors(note_id: str, by: str = "weight") -> str:
    """Rank neighbors by weight or confidence."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid = manager._parse_note_id(note_id)
    if nid is None:
        return f"Invalid note ID: {note_id}"
    ranked = manager.rank_neighbors(nid, by=by)
    if not ranked:
        return "No neighbors found."
    lines = [f"Neighbors ranked by {by}:\n"]
    for i, r in enumerate(ranked, 1):
        lines.append(f"  {i}. note-{r['id']} (w={r['weight']}, c={r.get('confidence','?')}) {r['title'] or r['content'][:60]}")
    return "\n".join(lines) + _REMINDER


@server.tool(
    description=(
        "Compute the similarity of the tool call's arguments, not the notes' content. "
        "Returns both notes' content so the agent can judge similarity. "
        "The agent should read both, decide a similarity score (0-1), "
        "then call link_notes with the appropriate weight and confidence."
    )
)
def compute_similarity(note_id_a: str, note_id_b: str) -> str:
    """Return both notes for agent-driven semantic similarity comparison."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    nid_a = manager._parse_note_id(note_id_a)
    nid_b = manager._parse_note_id(note_id_b)
    if nid_a is None or nid_b is None:
        return "One or both note IDs are invalid."
    rows = manager.storage.connection.cursor().execute(
        "SELECT id, topic, kind, content, title FROM notes WHERE id IN (?, ?)",
        (nid_a, nid_b),
    ).fetchall()
    if len(rows) != 2:
        return "One or both notes not found."
    result = []
    for r in rows:
        result.append(f"--- note-{r['id']} ({r['topic']}/{r['kind']}) ---")
        if r["title"]:
            result.append(f"Title: {r['title']}")
        result.append(r["content"])
    result.append("")
    result.append("Agent: decide a similarity score (0-1) and call link_notes with weight=<score>.")
    return "\n".join(result)


@server.tool(
    description=(
        "Rerank a list of note IDs by relevance to a query. "
        "Returns the query and each note's content so the agent can reorder them. "
        "The agent should read all notes, then return them in relevance order."
    )
)
def rerank(query: str, note_ids: list) -> str:
    """Return query + note contents for agent-driven reranking."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    ids = []
    for nid in note_ids:
        parsed = manager._parse_note_id(str(nid))
        if parsed is not None:
            ids.append(parsed)
    if not ids:
        return "No valid note IDs provided."
    placeholders = ",".join("?" for _ in ids)
    rows = manager.storage.connection.cursor().execute(
        f"SELECT id, topic, kind, content, title FROM notes WHERE id IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()
    parts = [f"Query: {query}", f"Candidate notes ({len(rows)}):\n"]
    for r in rows:
        parts.append(f"--- note-{r['id']} ({r['topic']}/{r['kind']}) ---")
        if r["title"]:
            parts.append(f"Title: {r['title']}")
        parts.append(r["content"][:500])
        parts.append("")
    parts.append("Agent: reorder the note IDs by relevance to the query and return them.")
    return "\n".join(parts)


@server.tool(
    description=(
        "Decay edge weights by a factor. "
        "All auto-link weights are multiplied by <factor> (default 0.9). "
        "Optionally limit to a specific planet."
    )
)
def edge_decay(factor: float = 0.9, planet: str | None = None) -> str:
    """Apply weight decay to auto-links."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.edge_decay(factor=factor, planet=planet)
    return f"Decayed {result['decayed']} edge(s) by factor {result['factor']}."


@server.tool(
    description=(
        "Prune edges below a weight threshold. "
        "Removes auto-links with weight < threshold (default 0.05). "
        "Optionally limit to a specific planet."
    )
)
def edge_prune(threshold: float = 0.05, planet: str | None = None) -> str:
    """Remove auto-links below weight threshold."""
    from storage.sessions import SessionManager
    from storage.db import StorageManager
    storage = StorageManager(get_db_path())
    manager = SessionManager(storage)
    result = manager.edge_prune(threshold=threshold, planet=planet)
    return f"Pruned {result['pruned']} edge(s) below threshold {result['threshold']}."


# ── Code Graph MCP Tools ──────────────────────────────────────────


_CODE_INDEXER = None  # Global or re-created per call


def _get_code_indexer(project_root: str = "") -> "CodeIndexer | None":
    """Get or create a CodeIndexer for the given project root."""
    global _CODE_INDEXER
    try:
        from indexer import CodeIndexer
        db_path = _resolve_db_path()
        if _CODE_INDEXER is None:
            _CODE_INDEXER = CodeIndexer(db_path)
        return _CODE_INDEXER
    except Exception as e:
        return None


@server.tool(
    description=(
        "Index or re-index a project's source code into the code knowledge graph. "
        "Scans source files using tree-sitter (306 languages supported) "
        "and builds a symbol graph of functions, classes, methods, calls, and imports. "
        "Run this once per project to enable code_search, code_node, etc."
    )
)
def code_init(project_root: str) -> str:
    """Index a project's source code into the code knowledge graph."""
    import os
    if not os.path.isdir(project_root):
        return f"Directory not found: {project_root}"

    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        result = indexer.index_project(project_root, max_workers=4)
        return (
            f"Indexed {result['files']} files, {result['symbols']} symbols, "
            f"{result['edges']} edges in {result['elapsed']:.1f}s"
        )
    finally:
        indexer.close()


@server.tool(
    description=(
        "List all indexed code symbols, with optional project filter. "
        "Returns symbols with file locations and line numbers."
    )
)
def code_list(limit: int = 100, offset: int = 0) -> str:
    """List all code symbols in the knowledge graph."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            return "No code project indexed yet. Run `code_init` first."
        results = indexer.list_symbols(limit=limit, offset=offset)
        if not results:
            return "No symbols found."
        total = stats.get("symbol_count", 0)
        parts = [f"Symbols {offset+1}-{offset+len(results)} of {total}:\n"]
        for r in results:
            loc = f"{r['file_path']}:{r['start_line']}-{r['end_line']}"
            parts.append(f"  [{r['id']}] {r['symbol_type']} **{r['symbol_name']}**  ({loc})")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(
    description=(
        "Search code symbols by name or signature. "
        "Returns matching functions, classes, methods with file locations and line numbers. "
        "Use this to find where code is defined before reading it."
    )
)
def code_search(query: str, limit: int = 20) -> str:
    """Search for code symbols across the indexed codebase."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        results = indexer.search_symbols(query, limit=limit)
        if not results:
            return f"No symbols match '{query}'. Try a different term or run `code_init` to index a project."
        parts = [f"Found {len(results)} symbol(s):\n"]
        for r in results:
            loc = f"{r['file_path']}:{r['start_line']}-{r['end_line']}"
            sig = f" {r['signature']}" if r.get('signature') else ""
            parts.append(f"  [{r['id']}] {r['symbol_type']} **{r['symbol_name']}**{sig}  ({loc})")
            if r.get('docstring'):
                parts.append(f"       doc: {r['docstring'][:150]}")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(
    description=(
        "Get detailed information about a specific code symbol by its ID or name. "
        "Returns source file, location, full signature, docstring, and caller/callee info. "
        "Use after code_search to drill into a specific symbol."
    )
)
def code_node(symbol_identifier: str) -> str:
    """Get details about a specific code symbol."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        # Try as numeric ID first
        sym = None
        try:
            sid = int(symbol_identifier)
            sym = indexer.get_symbol(sid)
        except ValueError:
            pass
        if not sym:
            symbols = indexer.get_symbol_by_name(symbol_identifier)
            if not symbols:
                return f"Symbol not found: {symbol_identifier}. Run `code_init` first or try `code_search`."
            sym = symbols[0]
            if len(symbols) > 1:
                parts = [f"Multiple symbols named '{symbol_identifier}':\n"]
                for s in symbols:
                    parts.append(f"  [{s['id']}] {s['symbol_type']} in {s['file_path']}:{s['start_line']}")
                return "\n".join(parts)

        # Get callers
        callers = indexer.get_callers(sym['symbol_name'])
        callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])

        parts = [
            f"**{sym['symbol_type']}** `{sym['symbol_name']}`",
            f"  File: {sym['file_path']}:{sym['start_line']}-{sym['end_line']}",
            f"  Language: {sym['language']}",
        ]
        if sym.get('signature'):
            parts.append(f"  Signature: {sym['signature']}")
        if sym.get('docstring'):
            parts.append(f"  Doc: {sym['docstring']}")
        if callers:
            parts.append(f"\n  Callers ({len(callers)}):")
            for c in callers[:10]:
                parts.append(f"    {c['symbol_type']} {c['symbol_name']} ({c['edge_file']}:{c['line_number']})")
        if callees:
            parts.append(f"\n  Calls ({len(callees)}):")
            for c in callees[:10]:
                parts.append(f"    {c['from_name']} (line {c['line_number']})")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(
    description=(
        "Find all code symbols that call a given function or method name. "
        "Returns the callers with their file locations. "
        "Use this to understand how a function is used before modifying it."
    )
)
def code_callers(symbol_name: str) -> str:
    """Find what calls a given symbol."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        results = indexer.get_callers(symbol_name)
        if not results:
            return f"No callers found for '{symbol_name}'."
        parts = [f"Callers of `{symbol_name}` ({len(results)}):\n"]
        for r in results:
            parts.append(f"  {r['symbol_type']} `{r['symbol_name']}` in {r['edge_file']}:{r['line_number']}")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(
    description=(
        "Find what a given function or method calls. Shows callees with file locations. "
        "Use this to understand a function's dependencies."
    )
)
def code_callees(symbol_name: str, file_path: str = "") -> str:
    """Find what a given symbol calls."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        results = indexer.get_callees(symbol_name, file_path)
        if not results:
            return f"No callees found for '{symbol_name}'."
        parts = [f"Callees of `{symbol_name}` ({len(results)}):\n"]
        for r in results:
            parts.append(f"  {r['from_name']} at {r['file_path']}:{r['line_number']}")
        return "\n".join(parts)
    finally:
        indexer.close()


@server.tool(
    description=(
        "Show code graph indexing status and stats. "
        "Returns how many files, symbols, and edges are indexed."
    )
)
def code_status() -> str:
    """Show code graph indexing status."""
    from indexer import CodeIndexer
    db_path = _resolve_db_path()
    indexer = CodeIndexer(db_path)
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            return "No code project indexed yet. Run `code_init` with a project root path."
        return (
            f"Project: {stats.get('name', '?')}\n"
            f"  Root: {stats.get('root_path', '?')}\n"
            f"  Files: {stats['file_count']}\n"
            f"  Symbols: {stats['symbol_count']}\n"
            f"  Edges: {stats['edges']}\n"
            f"  Last indexed: {stats.get('last_indexed', 'never')}"
        )
    finally:
        indexer.close()


# ── End Code Graph Tools ──────────────────────────────────────────

def main():
    server.run()


if __name__ == "__main__":
    main()
