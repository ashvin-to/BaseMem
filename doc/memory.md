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

# Get agent-ready context before answering
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
| Tool | Description |
|------|-------------|
| `getContext(topic, query)` | Compact pre-answer memory block |
| `read_planet(topic)` | Full planet details with all notes |
| `list_planets()` | Discover what topics exist |
| `search_nodes(query)` | Full-text search across all content |
| `search_notes(topic, kind, query)` | Filtered note search |
| `get_node(nodeId)` | Read any node by ID |

### Writing
| Tool | Description |
|------|-------------|
| `update_planet(topic, ...)` | Update or create a planet |
| `logInteraction(topic, ...)` | Persist decision, fact, state change, next step |
| `link_notes(fromNoteId, toNoteId, linkType)` | Connect two notes |
| `link_planets(fromPlanet, toPlanet, relation)` | Connect two planets |
| `set_memory_state(topic, state)` | Set hot/warm/compacted |

### Graph Navigation
| Tool | Description |
|------|-------------|
| `get_note_neighbors(noteId)` | Find all notes linked to a note |
| `get_planet_links(planet)` | Find all planets linked to a planet |
| `get_neighbors_weighted(noteId, depth, minWeight)` | Recursive weighted traversal |
| `get_subgraph(noteId, depth, minWeight)` | Extract structured subgraph |
| `rank_neighbors(noteId, by)` | Sort neighbors by weight or confidence |

### Agent-Driven Intelligence
| Tool | Description |
|------|-------------|
| `compute_similarity(noteIdA, noteIdB)` | Returns both notes for agent to judge similarity |
| `rerank(query, noteIds)` | Returns query + notes for agent to reorder by relevance |

### Lifecycle
| Tool | Description |
|------|-------------|
| `summarize_planet(topic)` | Return all notes for agent summarization |
| `compact_planet(topic)` | Keep summaries + 30 recent notes |
| `edge_decay(factor, planet)` | Multiply all auto-link weights by factor |
| `edge_prune(threshold, planet)` | Remove auto-links below weight threshold |

## CLI Commands

```
mem planet create/read/set/delete/compact/summarize/link/set-state
mem note add/link/neighbors
mem search
mem agent-context
mem list-planets
mem session turn/context/read/sync
mem recompute-links
mem edge decay/prune
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
```

Default location: `~/.basemem/basemem.db`
