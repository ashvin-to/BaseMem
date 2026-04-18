# BaseMem: AI Knowledge Base System

A lightweight knowledge graph plugin/middleware with token-optimized memory, hybrid retrieval (BM25 + Vector), and intelligent context packaging. **Designed as a plugin for existing chat interfaces** (Claude Code, Copilot, Gemini CLI, etc.) — not a standalone chat system.

## Quick Start

### Installation

```bash
pip install -e .
```

### Basic Usage

```bash
# Add knowledge to the base
kb add "Machine learning is a subset of artificial intelligence"

# Add a large file (like a technical manual or PDF transcript)
kb add --file path/to/document.txt --source "manual"

# Log an AI turn (Log + Summarize + Link)
kb session turn "my-topic" "Technical response content..." --sender ai

# Read full project history
kb session read "my-topic"

# Search for information
kb search "what is machine learning"

# Ask a question (full RAG pipeline)
kb ask "explain machine learning"

# Explore the knowledge graph
kb graph <node-id>

# View statistics
kb stats
```

## Ingesting AI Chat History

BaseMem is optimized to store and link your previous AI conversations. 

### Ingesting Gemini CLI History
To bring a full Gemini session into your graph, point the tool to your local `.gemini` tmp folder:
```bash
kb session ingest "topic-name" --file "~/.gemini/tmp/basemem/chats/session-timestamp.json"
```
*Tip: Use `kb session ingest` instead of `kb add` for chat history to keep the graph compact and avoid fragmentation.*

## Architecture

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
