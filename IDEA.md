# AI Knowledge Base System (Obsidian-like Graph + Token-Optimized Memory Layer) — v2

---

## System Architecture

### Core Pipeline

```text
CLI Layer (kb commands)
        |
        v
Context Orchestrator (Token Budget + Ranking)
        |
        v
+-------------------+-------------------+------------+
|                   |                   |
v                   v                   v
Retrieval Engine   Memory Store      Graph Engine
(BM25 + Vector)    (Nodes/Edges)     (Traversal & Links)
        \              |              /
         \             |             /
          \            |            /
           +-----------------------+
                    |
                    v
     Processing Pipeline (Async Workers)
                    |
                    v
     Structured Knowledge Store Layer
                    |
                    v
     SQLite + FTS5 + Vector Index (Hybrid)
```

---

## 1. Design Principles

- Optimize retrieval, not storage
- Convert raw chat → structured knowledge
- Combine symbolic + semantic memory
- Use graph + embeddings together
- Continuously improve via feedback loops
- Strict token-budgeted context building

---

## 2. CLI Layer

```bash
kb add "text"
kb search "query"
kb ask "question"
kb graph "node"
kb explain "concept"
```

### Key Feature
- `kb ask` = full RAG pipeline (retrieve → generate → store result)

---

## 3. Context Orchestrator (Core Intelligence Layer)

### Responsibilities
- Token budgeting
- Deduplication
- Ranking + diversity control
- Structured context formatting

### Output Format

```text
[Concept]
Binary Search → O(log n)

[Related]
- Divide & Conquer
- Sorted Arrays

[Facts]
- Works only on ordered data

[Example]
- Code or explanation snippet
```

---

### Retrieval Flow

```text
Query
  ↓
BM25 search (top 50)
  ↓
Vector search (top 50)
  ↓
Merge + deduplicate
  ↓
Cross-encoder rerank (top 10)
  ↓
Token-aware context packing
```

---

## 4. Retrieval Engine (Hybrid Required)

- BM25 → exact keyword matching
- Vector search → semantic similarity
- Reranker → final precision filter

```python
def retrieve(query):
    bm25 = bm25_search(query, top_k=50)
    vec = vector_search(query, top_k=50)

    merged = merge(bm25, vec)
    ranked = rerank(query, merged)

    return ranked[:10]
```

---

## 5. Memory System

### Stored Entities

- Raw chat logs
- Processed knowledge nodes
- Summarized clusters
- Metadata + usage stats

---

### Node Types

```python
NodeType = [
    "concept",
    "fact",
    "summary",
    "conversation",
    "task",
    "question",
    "example"
]
```

---

### Node Schema

```text
id
title
content
type
keywords
embedding
weight
created_at
last_accessed
decay_score
```

---

## 6. Processing Pipeline (Async)

```text
Raw Chat
  ↓
Semantic Chunking
  ↓
Entity + Keyword Extraction
  ↓
Optional LLM Summarization
  ↓
Node Creation
  ↓
Embedding Generation
  ↓
Graph Linking
  ↓
Storage
```

---

## 7. Graph Engine

### Edge Types

```python
EdgeType = [
    "is_a",
    "part_of",
    "related_to",
    "causes",
    "depends_on",
    "contradicts",
    "derived_from"
]
```

---

### Edge Schema

```text
from_id
to_id
type
weight
confidence
created_at
```

---

### Graph Functions

- get_neighbors()
- get_subgraph(depth)
- get_shortest_path()
- get_clusters()

---

### Edge Weight Formula

```text
weight = similarity × usage × recency
```

---

## 8. Linking Strategy

- Embedding similarity (>0.75)
- Keyword overlap (Jaccard)
- Co-occurrence reinforcement
- Time-based decay pruning

---

## 9. Storage Layer

### SQLite Tables

```text
Nodes:
id | title | content | type | weight | timestamps

Edges:
from_id | to_id | type | weight

Chats:
chat_id | raw_text | timestamp
```

### Vector Layer (Required Upgrade)

- FAISS (local)
- OR Qdrant (scalable)

---

## 10. Context Optimization

- Deduplication
- Compression
- Diversity enforcement
- Token-aware packing

---

## 11. Hierarchical Memory

```text
Level 1 → Raw nodes
Level 2 → Cluster summaries
Level 3 → Meta summaries
```

---

## 12. Forgetting System (CRITICAL)

```text
decay_score = f(age, usage, recency)
```

- Low → archive
- Medium → deprioritize
- High → reinforce

---

## 13. Feedback Loop

Tracks:

- Which nodes are used in answers
- Query success rate
- Follow-up behavior

Then adjusts:

- Node weights
- Edge weights
- Ranking priority

---

## 14. Async Workers

- ingestion_worker
- embedding_worker
- graph_worker
- summarization_worker

Queue-based system (Redis / asyncio / Celery)

---

## 15. CLI Expansion

```text
kb add
kb search
kb ask   ← core feature
kb graph
kb explain
```

---

## 16. `kb ask` Pipeline

```text
User Question
  ↓
Hybrid Retrieval
  ↓
Context Orchestrator
  ↓
LLM Response
  ↓
Store Answer as Node
  ↓
Link to Knowledge Graph
```

---

## 17. Visualization Layer

- Node importance scaling
- Heatmap (usage frequency)
- Time-based filtering
- Expandable subgraphs
- Cluster highlighting

---

## 18. System Evolution

### Phase 1
- SQLite + FTS5
- Basic BM25

### Phase 2
- Vector DB integration
- Reranker added

### Phase 3
- Full graph DB (Neo4j optional)
- Multi-device sync

---
