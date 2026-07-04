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

# Search across all content
mem search "what is machine learning"

# View your planets
mem session context

# Ingest AI chat history
mem session sync "topic-name" --agent-id "your-unique-suffix"
```

## MCP Tools

### Context & Discovery
| Tool | Parameters | Description |
|------|-----------|-------------|
| `getContext` | `topic`, `project`, `query` | Call for mid-session context refresh or when switching topics. Context is automatically injected at session start via the SessionStart hook. |
| `read_planet` | `topic` | Full planet details with all notes |
| `list_planets` | — | Discover what topics exist |
| `search_nodes` | `query`, `limit` | Full-text search across all content |
| `search_notes` | `topic`, `kind`, `query`, `limit` | Filtered note search |
| `get_node` | `nodeId` | Read any node by ID |

### Writing
| Tool | Parameters | Description |
|------|-----------|-------------|
| `update_planet` | `topic`, `currentState`, `nextStep`, `status`, `goal`, `filePath`, `command`, `handoff` | Update or create a planet |
| `logInteraction` | `topic`, `decision`, `fact`, `summary`, `currentState`, `nextStep`, `activity` | Persist decision, fact, state change, activity — all in one call |
| `link_notes` | `fromNoteId`, `toNoteId`, `linkType`, `weight` | Connect two notes |
| `link_planets` | `fromPlanet`, `toPlanet`, `relation`, `weight` | Connect two planets |
| `note_update` | `noteId`, `pinned`, `tags` | Set pinned status (true/false) and/or replace comma-separated tags. At least one of `pinned` or `tags` required. |
| `set_memory_state` | `topic`, `state` | Set hot/warm/compacted |

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

These two tools rely on agent-driven semantic judgment rather than deterministic computation.
They are only registered when `BASEMEM_ENABLE_ADVANCED_TOOLS=1` or `BASEMEM_ENABLE_ADVANCED_TOOLS=true` is set.
Enable them when actively curating note quality; omit them for a leaner tool list in daily development.

### Lifecycle
| Tool | Parameters | Description |
|------|-----------|-------------|
| `summarize_planet` | `topic`, `limit` | Return all notes for agent summarization |
| `compact_planet` | `topic` | Keep summaries + 30 recent notes |
| `edge_maintain` | `planet`, `decayFactor`, `pruneThreshold` | Apply weight decay (multiply all auto-link weights by factor) and/or prune edges below a weight threshold. Decay runs before prune so pruning reflects decayed weights. At least one of `decayFactor` or `pruneThreshold` required. |

## CLI Commands

```
mem planet create/read/set/delete/compact/summarize/link/set-state
mem note add/link/neighbors
mem search
mem agent-context
mem list-planets
mem session turn/context/read/sync
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

## Configuration

```bash
export BASEMEM_DB_PATH="./data/basemem.db"
export BASEMEM_ENABLE_ADVANCED_TOOLS=1  # enables compute_similarity + rerank tools
```

Default location: `~/.basemem/basemem.db`
