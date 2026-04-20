# BaseMem: AI Knowledge Base System

A lightweight knowledge graph plugin/middleware with token-optimized memory, hybrid retrieval (BM25 + Vector), and intelligent context packaging. **Designed as a plugin for existing chat interfaces** (Claude Code, Codex, Gemini CLI, etc.) rather than a standalone chat system.

The critical integration rule is simple:

1. After the first user prompt, read the knowledge base before the first answer.
2. Pass that retrieved context into the agent prompt or expose it as a tool.
3. Write durable updates back after the answer.

BaseMem now exposes a canonical pre-answer context command for that workflow:

```bash
kb agent-context --topic "project-name" --query "what am I working on?"
```

## Quick Start

### Installation (One-Command)

Simply run the setup script to make the `kb` command available globally:

```bash
chmod +x setup.sh && ./setup.sh
```

### Basic Usage (Global)

Now you can go to **any folder** and start a new project memory:

```bash
cd ~/my-project
kb session bootstrap "project-name"
```

### Add a large file (like a technical manual or PDF transcript)
```bash
kb add --file path/to/document.txt --source "manual"
```

### Log an AI turn (Log + Summarize + Link)
```bash 
kb session turn "my-topic" "Technical response content..." --sender ai
```

### Get agent-ready context before answering
```bash
kb agent-context --topic "my-topic" --query "current bug and next step"
```

### Read full project history
```bash
kb session read "my-topic"
```

### Search for information
```bash
kb search "what is machine learning"
```

### Ask a question (full RAG pipeline)
```bash
kb ask "explain machine learning"
```

### Explore the knowledge graph
```
kb graph <node-id>
```

### View statistics
```
kb stats
```
```

## Ingesting AI Chat History

BaseMem is optimized to store and link your previous AI conversations. 

### Multi-Agent Autonomous Sync
To automatically find your current Gemini CLI session file and sync the **entire high-detail transcript** into your private agent history node:
```bash
kb session sync "topic-name" --agent-id "your-unique-suffix"
```

### Manual Ingestion
To manually bring a full Gemini session into your graph from a specific file:
```bash
kb session ingest "topic-name" --file "/home/zoro/.gemini/tmp/basemem/chats/session-timestamp.json"
```

## Universal Agent Integration

The agent does not automatically know your knowledge base. Your launcher and host instructions must make the agent check memory after the first user prompt and before the first answer.

### Shell Wrapper

Use `ai-wrapper.sh` as the universal adapter:

```bash
./ai-wrapper.sh context my-topic
./ai-wrapper.sh run my-agent-command
./ai-wrapper.sh my-agent-command
```

During `run`, the wrapper:

- calls `kb agent-context`
- exports `BASEMEM_CONTEXT`
- writes the same content to `BASEMEM_CONTEXT_FILE`
- optionally injects the context via `BASEMEM_PROMPT_FLAG`
- optionally pipes the context via stdin when `BASEMEM_USE_STDIN=1`
- compacts and syncs transcript history after the agent exits

Examples:

```bash
BASEMEM_TOPIC=my-topic BASEMEM_PROMPT_FLAG=--prompt ./ai-wrapper.sh my-agent
BASEMEM_TOPIC=my-topic BASEMEM_USE_STDIN=1 ./ai-wrapper.sh my-agent
cat "$BASEMEM_CONTEXT_FILE"
```

### Default Launch Style

`setup.sh` configures shell aliases for the real command names:

- `codex`
- `claude`
- `gemini`

So the intended launch is:

```bash
BASEMEM_TOPIC=my-topic codex
BASEMEM_TOPIC=my-topic claude
BASEMEM_TOPIC=my-topic gemini
```

Those aliases route the process through `ai-wrapper.sh`, export the BaseMem context, and install host guidance so the agent checks the KB after the first prompt and before the first answer.

### Installed Helpers

Running `./setup.sh` installs:

- `kb`
- `basemem-ai`

`setup.sh` also installs a local Codex skill at `~/.codex/skills/basemem-memory` and a Gemini extension skill at `~/.gemini/extensions/00-basemem/skills/basemem-memory`.

### MCP Tools

If your host supports MCP tools, use the server in `src/basemem/mcp/server.py`. The important tools are:

- `get_agent_context(topic, query="")`
- `read_planet(topic)`
- `log_turn(topic, content, agent_id="default", sender="ai")`
- `update_planet(...)`
- `add_note(...)`

Recommended host policy:

1. Call `get_agent_context` after the first user prompt and before the first model answer.
2. Include that output in the working context.
3. After the answer, call `log_turn` and optionally `update_planet` or `add_note`.

## Architecture

BaseMem has been optimized into a **Zero-RAM "Dumb Storage" Layer** by default. Heavy AI models (like Torch, Transformers, FAISS) have been stripped from the core execution path to ensure it uses ~35MB RAM. All "intelligence" (summaries, keywords) is provided by the connected AI Agent, and Semantic Gravity uses fast Keyword Overlap instead of Vector Math.

### Core Components

1. **Storage Layer** (`storage/`)
   - SQLite + FTS5 for full-text search
   - Persistent node and edge storage
   - **Session Management**: Evolving rolling summaries and linked history.

2. **Retrieval Engine** (`retrieval/`)
   - BM25 for keyword matching
   - Vector search for semantic similarity
   - Hybrid merging and ranking

3. **Graph Engine** (`graph/`)
   - Node and edge management
   - Graph traversal (neighbors, paths, subgraphs)
   - **Semantic Gravity**: Automatic vector-based linking between related projects.

4. **Context Orchestrator** (`orchestrator/`)
   - Token budgeting
   - Deduplication and ranking
   - Diversity control
   - Structured context formatting

5. **Processing Pipeline** (`processing/`)
   - Async text ingestion
   - Semantic chunking
   - Automatic linking
   - **Local Summarization**: Transformers-based (BART/T5) background processing.

6. **Web Hub & API** (`server.py`)
   - Flask-based REST API for all commands.
   - **Obsidian Galaxy**: Dynamic D3.js visualization with Orbit mode and interactive node management.

7. **CLI Interface** (`cli/`)
   - User-friendly command line interface
   - **Session Commands**: turn, bootstrap, ingest, read, review.

## Data Models

### Node
```python
@dataclass
class Node:
    id: str
    title: str
    content: str
    node_type: NodeType  # concept, fact, summary, conversation, task, question, example
    keywords: List[str]
    embedding: Optional[List[float]]
    weight: float
    created_at: datetime
    last_accessed: datetime
    decay_score: float
    metadata: Dict[str, Any]
```

### Edge
```python
@dataclass
class Edge:
    from_id: str
    to_id: str
    edge_type: EdgeType  # is_a, part_of, related_to, causes, depends_on, contradicts, derived_from
    weight: float
    confidence: float
    created_at: datetime
    metadata: Dict[str, Any]
```

## Retrieval Pipeline

```
Query
  ↓
BM25 search (keyword matching) → top 50 results
  ↓
Vector search (semantic similarity) → top 50 results
  ↓
Merge and deduplicate
  ↓
Rank by: similarity × weight × decay_score
  ↓
Token-aware context packing
  ↓
Structured output formatting
```

## Project Structure

```
BaseMem/
├── src/basemem/
│   ├── models.py              # Core data classes
│   ├── storage/
│   │   ├── db.py              # SQLite storage manager
│   │   └── sessions.py        # Session & history logic
│   ├── retrieval/
│   │   ├── engine.py          # Hybrid retrieval
│   │   ├── bm25.py            # BM25 implementation
│   │   └── vector.py          # Vector search
│   ├── graph/
│   │   └── engine.py          # Graph operations (Semantic Gravity)
│   ├── orchestrator/
│   │   └── context.py         # Context orchestration
│   ├── processing/
│   │   ├── pipeline.py        # Main pipeline
│   │   ├── workers.py         # Async workers
│   │   └── summarizer.py      # Local BART/T5 summarizer
│   ├── mcp/
│   │   └── server.py          # Model Context Protocol server
│   └── cli/
│       └── main.py            # CLI commands
├── tests/
│   └── test_basemem.py       # Unit tests
├── kb.py                       # Entry point
├── graph_visualization.html    # Interactive Web UI
├── AGENTS.md                  # Universal AI Agent instructions
├── requirements.txt            # Dependencies
└── pyproject.toml             # Project metadata
```

## System Evolution

### Phase 1 (Complete)
- ✅ SQLite + FTS5 storage
- ✅ BM25 keyword search
- ✅ Sentence transformer embeddings
- ✅ Basic vector search
- ✅ CLI interface

### Phase 2 (Current)
- ✅ **Hierarchical Memory**: Level 1 (Summary) and Level 2 (Full History).
- ✅ **Web Hub**: Interactive "Obsidian Galaxy" visualizer.
- ✅ **Semantic Gravity**: Automatic vector-based project linking.
- ✅ **MCP Server**: Direct memory access for Claude/Gemini/Codex.
- ✅ **Local Summarization**: Background BART/T5 support.
- [ ] Decay-based forgetting system
- [ ] Cross-encoder reranking

### Phase 3 (Planned)
- Neo4j integration for larger graphs
- Multi-device synchronization
- Advanced visualization
- API server

## Configuration

Set environment variables:

```bash
export BASEMEM_DB_PATH="./data/basemem.db"
export BASEMEM_TOKEN_BUDGET="2000"
export BASEMEM_VECTOR_MODEL="all-MiniLM-L6-v2"
```

## Plugin Integration

Use BaseMem as middleware in your chat interface:

```python
# Example integration with any chat interface
from basemem.orchestrator.context import ContextOrchestrator
from basemem.storage.db import StorageManager

storage = StorageManager("knowledge.db")
orchestrator = ContextOrchestrator(storage, token_budget=2000)

# In your chat handler:
def handle_user_query(user_input, chat_history):
    # Get context from knowledge base
    context = orchestrator.orchestrate(user_input)
    
    # Augment prompt with context
    augmented_prompt = f"{context.to_prompt_format()}\n\nUser: {user_input}"
    
    # Send to your LLM (Claude, Copilot, etc.)
    response = your_llm.chat(augmented_prompt)
    
    return response
```

Works with:
- ✅ Claude (Claude.ai, Claude Code)
- ✅ GitHub Copilot & Copilot Chat
- ✅ Google Gemini CLI
- ✅ ChatGPT & OpenAI API
- ✅ Any LLM via custom integration

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Quality

```bash
black src/
ruff check src/
mypy src/
```

## License

MIT

## Contributing

Contributions welcome! See CONTRIBUTING.md for guidelines.
