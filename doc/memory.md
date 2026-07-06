# BaseMem: Memory System

Planets hold your task context, notes persist your decisions, and linked edges form a learnable graph.

## Quick Reference

```bash
# Create a planet
mem planet create "my-project" --goal "Build feature X" --state "Research phase"

# Update its status and next steps
mem planet set "my-project" --status active --next "Read the docs"

# Add a decision or fact
mem note add "my-project" --type decision -m "Use SQLite for persistence"

# Get agent-ready context (auto-injected at session start; use for mid-session refresh)
mem agent-context --topic "my-project" --query "what did we decide?"

# Read the full planet details
mem planet read "my-project"

# Log a turn (lightweight activity record)
mem session turn --topic "my-project" --message "Reviewed the PR" --agent-id "codex"

# Start a session, work, then let the next agent pick up context
mem session start "my-project" "Sprint 1" --agent-id "agent-a"
mem note add "my-project" --type decision -m "Use SQLite for persistence"
mem session end 1 --summary "Decided on SQLite"
# Next agent: context auto-includes last session summary via getContext

# Search across all content
mem search "what is machine learning"

# View your planets
mem session context

# Ingest AI chat history
mem session sync "topic-name" --agent-id "your-unique-suffix"
```

## MCP Tools

**29 core tools (34 with `BASEMEM_ENABLE_ADVANCED_TOOLS=1`).**

### Context & Discovery
| Tool | Parameters | Description |
|------|-----------|-------------|
| `getContext` | `topic`, `project`, `query` | Call for mid-session context refresh or when switching topics. Context is automatically injected at session start via the SessionStart hook. Response includes a sessions block (active sessions + last closed/paused session summary). |
| `read_planet` | `topic`, `limit` (optional) | Full planet details; pass `limit` to get raw notes for agent summarization (replaces the old `summarize_planet`) |
| `list_planets` | — | Discover what topics exist |
| `search_nodes` | `query`, `limit` | Full-text search across all content |
| `search_notes` | `topic`, `kind`, `query`, `limit` | Filtered note search |


### Writing
| Tool | Parameters | Description |
|------|-----------|-------------|
| `update_planet` | `topic`, `currentState`, `nextStep`, `status`, `goal`, `filePath`, `command`, `handoff` | Update or create a planet |
| `logInteraction` | `topic`, `decision`, `fact`, `summary`, `currentState`, `nextStep`, `activity` | Persist decision, fact, state change, activity — all in one call |
| `link` | `fromId`, `toId`, `linkType` (default=related), `weight` (default=1.0), `kind` (default=notes; or "planets") | Link two notes or two planets |
| `note_update` | `noteId`, `pinned`, `tags` | Set pinned status (true/false) and/or replace comma-separated tags. At least one of `pinned` or `tags` required. |

### Graph Navigation
| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_graph` | `noteId`, `depth` (default=1), `minWeight` (default=0.0), `ranked` (default=false) | Flat list of neighbors at depth=1 filtered by minWeight. When ranked=true, sorts by weight desc then confidence desc. When depth>1, returns full subgraph as JSON. |
| `get_planet_links` | `planet` | Find all planets linked to a planet |

### Agent-Driven Intelligence (optional tier)
| Tool | Parameters | Description |
|------|-----------|-------------|
| `compute_similarity` | `noteIdA`, `noteIdB` | Returns both notes for agent to judge similarity |
| `rerank` | `query`, `noteIds` | Returns query + notes for agent to reorder by relevance |
| `set_memory_state` | `topic`, `state` | Set hot/warm/compacted tier |
| `get_node` | `nodeId` | Read any node by ID |
| `code_list_projects` | `searchRoot` (optional) | Scan filesystem for all indexed code projects |

These five tools rely on agent-driven semantic judgment or are useful only during curation/debugging.
They are only registered when `BASEMEM_ENABLE_ADVANCED_TOOLS=1` or `BASEMEM_ENABLE_ADVANCED_TOOLS=true` is set.
Enable them for curation, debugging, or project discovery; omit them for a leaner tool list in daily development.

### Lifecycle
| Tool | Parameters | Description |
|------|-----------|-------------|
| `compact_planet` | `topic` | Keep summaries + 30 recent notes |
| `edge_maintain` | `planet`, `decayFactor`, `pruneThreshold` | Apply weight decay (multiply all auto-link weights by factor) and/or prune edges below a weight threshold. Decay runs before prune so pruning reflects decayed weights. At least one of `decayFactor` or `pruneThreshold` required. |

### Session Management
| Tool | Parameters | Description |
|------|-----------|-------------|
| `session_start` | `topic`, `title`, `agent_id` | Start a new session (returns session_id) |
| `session_end` | `session_id`, `summary` (optional), `hard` (default=false) | Close a session. When `hard=true`, also unpins all stamped notes and detaches stamped tasks |
| `session_resume` | `session_id`, `agent_id` | Resume a paused session |
| `session_read` | `session_id` | Full session details with expanded notes and tasks |
| `session_list` | `topic` (optional), `status` (optional) | List sessions, optionally filtered |

## CLI Commands

```
mem planet create/read/set/delete/compact/summarize/link/set-state
mem note add/link/neighbors
mem search
mem agent-context
mem list-planets
mem session turn/context/read/sync/start/end/pause/resume/list
mem recompute-links
mem edge maintain
mem export / mem import
```

## Data Models

### Planet

```python
{
    "topic": "str",              # unique slug
    "display_topic": "str",      # human-readable name
    "status": "str",             # active, paused, done, archived
    "goal": "str",               # high-level objective
    "current_state": "str",      # what's happening now
    "next_step": "str",          # immediate next action
    "next_steps": "list",        # JSON array of upcoming steps
    "files": "list",             # JSON array of relevant file paths
    "commands": "list",          # JSON array of useful commands
    "handoff": "str",            # handoff notes for the next session
    "aliases": "list",           # JSON array of alternative names
    "memory_state": "str",       # hot, warm, or compacted
}
```

### Session

```python
{
    "id": "int",
    "topic": "str",              # planet slug
    "title": "str",
    "status": "str",             # active, paused, closed
    "started_at": "str",         # ISO 8601
    "ended_at": "str",           # ISO 8601 (null if active)
    "last_active_at": "str",     # ISO 8601
    "summary": "str",            # closing summary (null if active)
    "agent_id": "str",           # agent that started/resumed the session
    "note_ids": "list[int]",     # JSON array of note IDs stamped during session
    "task_ids": "list[int]",     # JSON array of task IDs stamped during session
}
```

### Note

```python
{
    "id": "int",
    "topic": "str",              # planet slug
    "kind": "str",               # decision, fact, issue, question, concept, example, turn, summary
    "content": "str",
    "title": "str",
    "agent_id": "str",
    "status": "str",             # open, resolved, closed
    "turn_index": "int",
    "tags": "list[str]",         # comma-separated in storage
    "pinned": "bool",            # pinned notes survive compaction
    "session_id": "int|None",    # stamped when created during an active session
}
```

### Note Link

```python
{
    "from_note_id": "int",
    "to_note_id": "int",
    "link_type": "str",          # related, depends, implements, fixes, duplicates, supersedes, causes, blocks, tests, references, auto
    "weight": "float",           # 0-1
    "confidence": "float",       # 0-1 (auto links capped at similarity*1.5)
    "source": "str",             # auto or explicit
    "created_at": "str",
    "updated_at": "str",
}
```

### Planet Link

```python
{
    "from_planet_id": "int",
    "to_planet_id": "int",
    "relation": "str",           # related, depends, implements, fixes, duplicates, supersedes, causes, blocks, tests, references
    "weight": "float",           # 0-1
}
```

## Auto-Linking

When `add_note` is called, the new note is automatically linked to existing notes on the same planet using Jaccard similarity on keyword sets (threshold 0.2). Explicit links override auto links. Edge reinforcement increments auto-link weight by 0.05 on each co-access.

## Memory Tiers

- **hot** — active working notes (default)
- **warm** — stable knowledge, not recently accessed
- **compacted** — summarized by agent, only summary + 30 recent notes preserved

## Sessions

Sessions group related notes and tasks under a named work interval. When a note is added or a task is created/updated while a session is **active** on that planet, the note or task is automatically stamped with the session id.

### Auto-Recovery

`getContext` and `agent-context` automatically run session recovery before reporting: any session whose `last_active_at` is older than `BASEMEM_SESSION_TIMEOUT_HOURS` (default 24) is **paused** and a fact note is created recording the timeout. This prevents stale sessions from silently accumulating.

### Stamping

- **Notes**: `add_note` calls `get_active_session(topic, agent_id)` — the active session with a matching agent_id is selected. If found, the note is stamped.
- **Tasks**: `create_task` and `update_task` call `list_sessions(topic, status='active')` — the most recently active session on the planet is selected. Tasks don't carry an `agent_id`, so agent-scoped filtering is not applied.

### Context Block

Both `getContext` and `agent-context` include a **Sessions** block above the notes section, listing:
- Active sessions with their title, agent, and human-readable age
- The last closed or paused session with its summary, or the titles of its last 5 notes if no summary exists

## Configuration

```bash
export BASEMEM_DB_PATH="./data/basemem.db"
export BASEMEM_ENABLE_ADVANCED_TOOLS=1  # enables compute_similarity, rerank, set_memory_state, get_node, code_list_projects
export BASEMEM_SESSION_TIMEOUT_HOURS=24  # session auto-pause timeout (min 1)
```

Default location: `~/.basemem/basemem.db`
