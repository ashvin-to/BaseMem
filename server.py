"""Web server for BaseMem visualization and API"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from pathlib import Path
import sys
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.basemem.storage.db import StorageManager
from src.basemem.retrieval.engine import RetrievalEngine
from src.basemem.graph.engine import GraphEngine
from src.basemem.orchestrator.context import ContextOrchestrator
from src.basemem.storage.sessions import SessionManager
from src.basemem.processing.summarizer import LocalSummarizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize BaseMem components
db = StorageManager("basemem.db")
retrieval = RetrievalEngine(db)
graph = GraphEngine(db)
orchestrator = ContextOrchestrator(db)


@app.route("/api/graph", methods=["GET"])
def get_graph():
    """Get full graph data for visualization"""
    try:
        nodes = db.get_all_nodes()
        edges = []
        
        for node in nodes:
            edges.extend(db.get_edges(from_id=node.id))
        
        # Convert to JSON-serializable format
        nodes_data = [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content[:100] + "..." if len(n.content) > 100 else n.content,
                "type": n.node_type.value,
                "weight": n.weight,
                "keywords": n.keywords,
                "color": _get_node_color(n.node_type.value),
            }
            for n in nodes
        ]
        
        edges_data = [
            {
                "id": f"{e.from_id}-{e.to_id}",
                "source": e.from_id,
                "target": e.to_id,
                "type": e.edge_type.value,
                "weight": e.weight,
                "confidence": e.confidence,
            }
            for e in edges
        ]
        
        return jsonify({
            "nodes": nodes_data,
            "edges": edges_data,
            "stats": graph.get_graph_stats(),
        })
    except Exception as e:
        logger.error(f"Error getting graph: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/node/<node_id>", methods=["GET"])
def get_node(node_id):
    """Get single node with neighbors"""
    try:
        node = db.get_node(node_id)
        if not node:
            return jsonify({"error": "Node not found"}), 404
        
        neighbors = graph.get_neighbors(node_id, depth=1)
        edges = db.get_edges(from_id=node_id)
        
        return jsonify({
            "node": {
                "id": node.id,
                "title": node.title,
                "content": node.content,
                "type": node.node_type.value,
                "keywords": node.keywords,
                "weight": node.weight,
            },
            "neighbors": [
                {
                    "id": n.id,
                    "title": n.title,
                    "type": n.node_type.value,
                }
                for n in neighbors.values()
            ],
            "edges": [
                {
                    "target": e.to_id,
                    "type": e.edge_type.value,
                    "weight": e.weight,
                }
                for e in edges
            ],
        })
    except Exception as e:
        logger.error(f"Error getting node {node_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search", methods=["POST"])
def search():
    """Search knowledge base"""
    try:
        data = request.get_json()
        query = data.get("query", "")
        
        if not query:
            return jsonify({"error": "Query required"}), 400
        
        results = retrieval.retrieve(query, top_k=10)
        
        return jsonify({
            "query": query,
            "results": [
                {
                    "id": r.node.id,
                    "title": r.node.title,
                    "content": r.node.content[:200] + "..." if len(r.node.content) > 200 else r.node.content,
                    "score": r.score,
                    "source": r.source,
                    "type": r.node.node_type.value,
                }
                for r in results
            ],
        })
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ask", methods=["POST"])
def ask():
    """Ask question (full RAG pipeline)"""
    try:
        data = request.get_json()
        query = data.get("query", "")
        
        if not query:
            return jsonify({"error": "Query required"}), 400
        
        context_packet = orchestrator.orchestrate(query)
        
        return jsonify({
            "query": query,
            "context": {
                "concept": context_packet.concept,
                "related": context_packet.related,
                "facts": context_packet.facts,
                "examples": context_packet.examples,
                "token_count": context_packet.token_count,
            },
        })
    except Exception as e:
        logger.error(f"Error orchestrating context: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
def stats():
    """Get knowledge base statistics"""
    try:
        stats = graph.get_graph_stats()
        nodes = db.get_all_nodes()
        
        return jsonify({
            **stats,
            "avg_node_weight": sum(n.weight for n in nodes) / len(nodes) if nodes else 0,
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/session/turn", methods=["POST"])
def session_turn():
    """Execute a complete session turn (log + summarize + export)"""
    try:
        data = request.get_json()
        topic = data.get("topic")
        message = data.get("message")
        summary = data.get("summary")
        sender = data.get("sender", "ai")
        model = data.get("model", "t5-small")

        if not topic or not message:
            return jsonify({"error": "Topic and message required"}), 400

        manager = SessionManager(db)
        manager.log_chat(topic, message, sender=sender)

        if summary:
            summary_text = summary
        else:
            history = manager.get_session_history(topic)
            summarizer = LocalSummarizer(model_name=model)
            summary_text = summarizer.summarize_chat_history(history)

        if summary_text:
            manager.update_summary(topic, summary_text)
            
            # Export to file
            output_file = f".basemem-{topic}-summary.md"
            with open(output_file, "w") as f:
                f.write(f"# Session Summary: {topic}\n\n")
                f.write(summary_text)
                f.write(f"\n\n---\n*Last Updated: {manager.get_or_create_session(topic).last_accessed.isoformat()}*")

            return jsonify({
                "status": "success",
                "summary": summary_text,
                "file": output_file
            })
        else:
            return jsonify({"error": "Summarization failed"}), 500
    except Exception as e:
        logger.error(f"Error in session turn: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/session/bootstrap", methods=["POST"])
def session_bootstrap():
    """Bootstrap a new project/topic"""
    try:
        data = request.get_json()
        topic = data.get("topic")
        target_path = data.get("path", ".") # Allow specifying a folder
        
        if not topic:
            return jsonify({"error": "Topic required"}), 400

        manager = SessionManager(db)
        manager.get_or_create_session(topic)

        # Create AGENTS.md in the target path
        agents_file = Path(target_path) / "AGENTS.md"
        content = f"""# Universal Agent Rules & Memory Protocol

## 🧠 Compact Memory Protocol
This project uses a 2-node hierarchical memory in BaseMem.

### 1. The Structure
- **Node A (Summary)**: Concise project status.
- **Node B (Main History)**: A single large node containing the entire chat history.

### 2. Mandatory Workflow
After EVERY response you give, you MUST run this command to update the memory:
```bash
kb session turn "{topic}" "<Brief log of this turn>" --sender ai
```

### 3. Start of Session
1. Read the .basemem-{topic}-summary.md file for context.
2. For deep technical details, read the Main History node:
   `kb session read "{topic}"`
"""
        with agents_file.open("w") as f:
            f.write(content)

        return jsonify({"status": "success", "topic": topic, "agents_file": str(agents_file.absolute())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/session/read/<topic>", methods=["GET"])
def session_read(topic):
    """Read the full history for a topic"""
    try:
        manager = SessionManager(db)
        # 1. Try deterministic ID first
        history_node_id = f"main-history-{topic.lower().replace(' ', '-')}"
        node = db.get_node(history_node_id)
        
        # 2. If not found, find the summary node and look for linked conversation nodes
        if not node:
            session_node = manager.get_or_create_session(topic)
            history = manager.get_session_history(topic)
            # Find the first node marked as main history
            node = next((n for n in history if n.metadata.get("is_main_history")), None)
            
            # 3. If still not found, just return the summary content as a fallback
            if not node:
                node = session_node

        if node:
            return jsonify({
                "topic": topic,
                "title": node.title,
                "content": node.content,
                "node_id": node.id
            })
        return jsonify({"error": "History not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/node/<node_id>", methods=["DELETE"])
def delete_node(node_id):
    """Delete a specific node"""
    try:
        db.delete_node(node_id)
        return jsonify({"status": "success", "deleted": node_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_node_color(node_type: str) -> str:
    """Map node type to color"""
    colors = {
        "concept": "#4CAF50",
        "fact": "#2196F3",
        "summary": "#FF9800",
        "conversation": "#9C27B0",
        "task": "#F44336",
        "question": "#FFC107",
        "example": "#00BCD4",
    }
    return colors.get(node_type, "#757575")


if __name__ == "__main__":
    logger.info("Starting BaseMem web server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
