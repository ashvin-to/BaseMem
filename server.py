"""Web server for BaseMem visualization and API (Storage Only Version)"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from pathlib import Path
import sys
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.basemem.storage.db import StorageManager
from src.basemem.graph.engine import GraphEngine
from src.basemem.orchestrator.context import ContextOrchestrator
from src.basemem.storage.sessions import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize BaseMem components (Lazily)
_db = None
_graph = None

def get_db():
    global _db
    if _db is None:
        # Default path in Home directory
        home = Path.home()
        db_path = home / ".basemem" / "basemem.db"
        _db = StorageManager(str(db_path))
    return _db

def get_graph():
    global _graph
    if _graph is None:
        _graph = GraphEngine(get_db())
    return _graph

@app.route("/", methods=["GET"])
def index():
    """Serve the galaxy visualization UI"""
    try:
        ui_path = Path(__file__).parent.parent.parent / "graph_visualization.html"
        with open(ui_path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error loading UI: {str(e)}", 500

@app.route("/api/graph", methods=["GET"])
def get_graph_data():
    """Get full graph data for visualization"""
    try:
        db_instance = get_db()
        graph_instance = get_graph()
        nodes = db_instance.get_all_nodes()
        edges = db_instance.get_edges()
        
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
            }
            for e in edges
        ]
        
        return jsonify({
            "nodes": nodes_data,
            "edges": edges_data,
            "stats": graph_instance.get_graph_stats(),
        })
    except Exception as e:
        logger.error(f"Error getting graph: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/node/<node_id>", methods=["GET"])
def get_node(node_id):
    """Get single node with neighbors"""
    try:
        db_instance = get_db()
        graph_instance = get_graph()
        node = db_instance.get_node(node_id)
        if not node:
            return jsonify({"error": "Node not found"}), 404
        
        neighbors = graph_instance.get_neighbors(node_id, depth=1)
        edges = db_instance.get_edges(from_id=node_id)
        
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

@app.route("/api/node/<node_id>", methods=["DELETE"])
def delete_node(node_id):
    """Delete a specific node"""
    try:
        db_instance = get_db()
        db_instance.delete_node(node_id)
        return jsonify({"status": "success", "deleted": node_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/node", methods=["POST"])
def create_node():
    """Manually create a new knowledge node"""
    try:
        data = request.get_json()
        from src.basemem.models import Node, NodeType
        import uuid
        
        node = Node(
            id=data.get("id") or f"manual-{uuid.uuid4().hex[:8]}",
            title=data.get("title", "New Node"),
            content=data.get("content", ""),
            node_type=NodeType(data.get("type", "concept")),
            keywords=data.get("keywords", [])
        )
        
        db_instance = get_db()
        db_instance.add_node(node)
        
        # Trigger auto-linking
        graph_instance = get_graph()
        graph_instance.auto_link_nodes(node.id)
        
        return jsonify({"status": "success", "node_id": node.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/session/turn", methods=["POST"])
def session_turn():
    """Log a complete turn and update summary"""
    try:
        data = request.get_json()
        topic = data.get("topic")
        message = data.get("message")
        summary = data.get("summary")
        agent_id = data.get("agent_id", "default")
        sender = data.get("sender", "ai")

        if not topic or not message:
            return jsonify({"error": "Topic and message required"}), 400

        db_instance = get_db()
        manager = SessionManager(db_instance)
        manager.log_chat(topic, message, sender=sender, agent_id=agent_id)

        if summary:
            session_node = manager.update_summary(topic, summary)
            return jsonify({"status": "success", "summary": summary})
        
        return jsonify({"status": "success", "logged": True})
    except Exception as e:
        logger.error(f"Error in session turn: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/session/bootstrap", methods=["POST"])
def session_bootstrap():
    """Bootstrap a new project/topic"""
    try:
        data = request.get_json()
        topic = data.get("topic")
        target_path = data.get("path", ".")
        if not topic: return jsonify({"error": "Topic required"}), 400

        db_instance = get_db()
        manager = SessionManager(db_instance)
        manager.get_or_create_session(topic)

        agents_file = Path(target_path) / "AGENTS.md"
        content = f"# AI Memory Protocol: {topic}\n\nStart: `kb session context` | Turn: `kb session turn` | Sync: `kb session sync`"
        with agents_file.open("w") as f: f.write(content)

        return jsonify({"status": "success", "topic": topic})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/session/read/<topic>", methods=["GET"])
def session_read(topic):
    """Read history for a topic"""
    try:
        db_instance = get_db()
        manager = SessionManager(db_instance)
        agent_id = request.args.get("agent_id", "default")
        
        node_id = f"history-{agent_id}-{topic.lower().replace(' ', '-')}"
        node = db_instance.get_node(node_id)
        
        if not node:
            # Fallback to shared summary
            node = manager.get_or_create_session(topic)

        if node:
            return jsonify({"topic": topic, "content": node.content})
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _get_node_color(node_type: str) -> str:
    """Map node type to color"""
    colors = {
        "concept": "#7c3aed",
        "fact": "#2196F3",
        "summary": "#f97316",
        "conversation": "#06b6d4",
        "task": "#F44336",
        "question": "#FFC107",
        "example": "#00BCD4",
    }
    return colors.get(node_type, "#757575")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
