# BaseMem Development Guide

## Architecture Overview

BaseMem follows a modular, layered architecture:

```
┌─────────────────────────────────┐
│      Web Hub / API (server.py)  │ ← Obsidian Galaxy UI
└────────────┬────────────────────┘
             │
┌────────────┴────────────────────┐
│      CLI Layer (main.py)        │ ← User interface & Session cmds
└────────────┬────────────────────┘
             │
┌────────────v────────────────────┐
│   Context Orchestrator          │ ← Token budgeting & ranking
└────────────┬────────────────────┘
             │
      ┌──────┴──────┬───────────────┐
      │             │               │
┌─────v──┐    ┌────v──────┐   ┌────v──────┐
│Retrieval│    │  Graph    │   │Processing │
│ Engine  │    │ Engine    │   │ (Summarizer)
└─────┬──┘    └────┬──────┘   └────┬──────┘
      │             │               │
  ┌───┴─────────────┴───────────────┴───┐
  │         Storage (SQLite)            │
  │     (db.py + sessions.py)           │
  └─────────────────────────────────────┘
```

## How to Extend

### 1. Add New Node Type
...

In `models.py`:
```python
class NodeType(str, Enum):
    # Add new type
    PAPER = "paper"
    VIDEO = "video"
```

Then update processing to handle it:
```python
# In processing/workers.py
node_type_map = {
    "abstract": NodeType.PAPER,
    "transcript": NodeType.VIDEO,
}
```

### 2. Add New Edge Type

In `models.py`:
```python
class EdgeType(str, Enum):
    # Add new relationship type
    EXTENDS = "extends"
    CITES = "cites"
```

### 3. Custom Retrieval Strategy

Create new file `retrieval/custom.py`:
```python
from typing import List, Tuple

class CustomRetriever:
    def __init__(self, storage):
        self.storage = storage
    
    def search(self, query: str, top_k: int = 50) -> List[Tuple[str, float]]:
        # Your custom logic
        pass

# Register in engine.py
def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
    custom = CustomRetriever(self.storage)
    results = custom.search(query, top_k=20)
    # Merge with other results
```

### 4. Custom Ranking Function

In `orchestrator/context.py`:
```python
def _custom_ranking_score(self, result: RetrievalResult) -> float:
    # Your custom scoring
    recency = 1 - (time.time() - result.node.created_at.timestamp()) / (365 * 24 * 3600)
    popularity = result.node.weight
    decay = result.node.decay_score
    
    return recency * popularity * decay * result.score
```

### 5. Add LLM Integration

Create `llm/client.py`:
```python
from openai import OpenAI

class LLMClient:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    def generate(self, prompt: str, context: ContextPacket) -> str:
        full_prompt = f"{context.to_prompt_format()}\n\n{prompt}"
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": full_prompt}]
        )
        return response.choices[0].message.content
```

Update CLI:
```python
@cli.command()
@click.argument('query')
@click.pass_context
def ask(ctx, query):
    orchestrator = ContextOrchestrator(ctx.obj['storage'])
    context = orchestrator.orchestrate(query)
    
    llm = LLMClient(os.getenv("OPENAI_API_KEY"))
    answer = llm.generate(query, context)
    
    click.echo(answer)
```

### 6. Add Visualization

Create `visualization/graph.py`:
```python
import networkx as nx
import matplotlib.pyplot as plt

def visualize_graph(storage, node_id: str, depth: int = 2):
    graph = GraphEngine(storage)
    
    # Get subgraph
    nodes, edges = graph.get_subgraph([node_id], depth=depth)
    
    # Build NetworkX graph
    G = nx.DiGraph()
    
    for node in nodes:
        G.add_node(node.id, title=node.title, type=node.node_type.value)
    
    for edge in edges:
        G.add_edge(edge.from_id, edge.to_id, relation=edge.edge_type.value)
    
    # Draw
    pos = nx.spring_layout(G)
    nx.draw(G, pos, with_labels=True)
    plt.show()
```

### 7. Vector DB Upgrade (FAISS → Qdrant)

Create `storage/vector_db.py`:
```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

class VectorStore:
    def __init__(self, collection_name: str = "nodes"):
        self.client = QdrantClient(":memory:")
        self.collection = collection_name
        
        # Create collection
        self.client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )
    
    def add(self, node_id: str, embedding: List[float]):
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=hash(node_id), vector=embedding, payload={"node_id": node_id})]
        )
    
    def search(self, embedding: List[float], limit: int = 10):
        results = self.client.search(
            collection_name=self.collection,
            query_vector=embedding,
            limit=limit
        )
        return results
```

## Testing

### Unit Tests

```python
# tests/test_retrieval.py
def test_hybrid_retrieval(temp_db):
    engine = RetrievalEngine(temp_db)
    
    # Add test data
    node = Node(title="Test", content="test content")
    temp_db.add_node(node)
    
    # Test retrieval
    results = engine.retrieve("test", top_k=10)
    assert len(results) > 0
    assert results[0].node.id == node.id
```

### Integration Tests

```python
# tests/test_integration.py
@pytest.mark.asyncio
async def test_full_pipeline(temp_db):
    # Add knowledge
    pipeline = ProcessingPipeline(temp_db)
    nodes = await pipeline.ingest_text("Sample text")
    
    # Search
    engine = RetrievalEngine(temp_db)
    results = engine.retrieve("sample")
    
    # Orchestrate
    orchestrator = ContextOrchestrator(temp_db)
    context = orchestrator.orchestrate("sample")
    
    assert len(results) > 0
    assert context.token_count > 0
```

## Performance Optimization

### 1. Index Optimization
```python
# Rebuild indexes periodically
retrieval_engine.rebuild_indexes()
```

### 2. Batch Operations
```python
# Bulk insert
nodes_to_add = [Node(...) for _ in range(1000)]
for node in nodes_to_add:
    storage.add_node(node)
retrieval_engine.rebuild_indexes()
```

### 3. Query Caching
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_retrieve(query: str, top_k: int):
    return retrieval_engine.retrieve(query, top_k)
```

### 4. Database Optimization
```python
# In db.py
def _vacuum_database(self):
    """Reclaim unused space"""
    cursor = self.connection.cursor()
    cursor.execute("VACUUM")
    self.connection.commit()
```

## Deployment

### Docker

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "basemem.api"]
```

Build and run:
```bash
docker build -t basemem .
docker run -v /data:/app/data -p 8000:8000 basemem
```

### API Server

Create `basemem/api.py`:
```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
storage = StorageManager()
orchestrator = ContextOrchestrator(storage)

@app.post("/ask")
async def ask(query: str):
    context = orchestrator.orchestrate(query)
    return JSONResponse({
        "query": query,
        "context": context.to_dict(),
        "tokens": context.token_count
    })

@app.get("/search")
async def search(q: str, top_k: int = 10):
    engine = RetrievalEngine(storage)
    results = engine.retrieve(q, top_k=top_k)
    return JSONResponse({
        "results": [r.to_dict() for r in results]
    })

# Run: uvicorn basemem.api:app --reload
```

## Debugging

### Enable Logging
```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
```

### Inspect Database
```python
storage = StorageManager()
nodes = storage.get_all_nodes()
print(f"Total nodes: {len(nodes)}")

for node in nodes[:5]:
    print(f"  {node.id}: {node.title}")
```

### Profile Performance
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Code to profile
results = retrieval_engine.retrieve(query, top_k=100)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(10)
```

## Best Practices

1. **Always rebuild indexes** after bulk operations
2. **Use batch inserts** for performance
3. **Regular cleanup** with decay_score pruning
4. **Monitor database size** with periodic VACUUM
5. **Test edge cases** (empty queries, missing nodes, etc.)
6. **Document custom extensions** clearly
7. **Use type hints** throughout
8. **Handle exceptions gracefully**

## Common Issues & Solutions

### Issue: FAISS import fails
**Solution**: Install FAISS correctly for your platform:
```bash
pip install faiss-cpu  # For CPU
pip install faiss-gpu  # For GPU
```

### Issue: Slow vector search
**Solution**: Use Qdrant or smaller embedding model:
```python
model = SentenceTransformer("all-MiniLM-L6-v2")  # 384 dims (faster)
```

### Issue: Database locked
**Solution**: Use WAL mode:
```python
self.connection.execute("PRAGMA journal_mode=WAL")
```

### Issue: Memory issues with large corpus
**Solution**: Use streaming with limit:
```python
results = retrieval_engine.retrieve(query, top_k=50)  # Reduce top_k
```

## Next Steps

1. Implement Phase 2 features
2. Add API server
3. Improve visualization
4. Optimize vector search
5. Add LLM integration
6. Implement feedback loops
7. Add multi-user support
