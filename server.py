"""Web server for BaseMem visualization and API"""

import json
import logging
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from .storage.db import StorageManager
from .graph.engine import GraphEngine
from .storage.sessions import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

_db = None
_graph = None

def get_db():
    global _db
    if _db is None:
        home = Path.home()
        db_path = home / ".basemem" / "basemem.db"
        _db = StorageManager(str(db_path))
    return _db

def get_graph():
    global _graph
    if _graph is None:
        _graph = GraphEngine(get_db())
    return _graph

def get_session():
    return SessionManager(get_db())

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


@app.route("/api/notes/graph", methods=["GET"])
def notes_graph():
    """Get all notes + links as D3 graph data, grouped by planet."""
    try:
        conn = get_db().connection
        planets = conn.execute(
            "SELECT topic, display_topic, status FROM planets ORDER BY updated_at DESC"
        ).fetchall()

        nodes = []
        edges = []

        for p in planets:
            slug = p["topic"]
            pid = f"planet-{slug}"
            nodes.append({
                "id": pid, "title": p["display_topic"] or slug,
                "type": "planet", "group": 0, "weight": 2,
                "color": _get_node_color("summary"),
            })

            note_rows = conn.execute(
                "SELECT id, kind, content, title, agent_id FROM notes WHERE topic = ? ORDER BY created_at DESC",
                (slug,),
            ).fetchall()

            for n in note_rows:
                nid = f"note-{n['id']}"
                label = n["title"] or n["content"][:60]
                nodes.append({
                    "id": nid, "title": label, "type": n["kind"],
                    "group": slug, "weight": 1,
                    "color": _get_note_color(n["kind"]),
                    "planet": slug,
                })
                edges.append({
                    "source": pid, "target": nid,
                    "type": "contains", "weight": 0.5,
                })

            links = conn.execute(
                """SELECT from_note_id, to_note_id, link_type, weight
                   FROM note_links
                   WHERE from_note_id IN (SELECT id FROM notes WHERE topic = ?)
                      OR to_note_id IN (SELECT id FROM notes WHERE topic = ?)""",
                (slug, slug),
            ).fetchall()

            for l in links:
                edges.append({
                    "source": f"note-{l['from_note_id']}",
                    "target": f"note-{l['to_note_id']}",
                    "type": l["link_type"],
                    "weight": l["weight"] or 1,
                })

        return jsonify({"nodes": nodes, "edges": edges, "stats": {"planets": len(planets), "notes": len(nodes) - len(planets)}})
    except Exception as e:
        logger.error(f"Error getting notes graph: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/notes/<int:note_id>", methods=["GET"])
def get_note_detail(note_id):
    """Get a single note with its linked neighbors."""
    try:
        conn = get_db().connection
        row = conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Note not found"}), 404

        mgr = get_session()
        neighbors = mgr.get_note_neighbors(note_id)

        return jsonify({
            "note": {
                "id": f"note-{row['id']}",
                "topic": row["topic"],
                "kind": row["kind"],
                "content": row["content"],
                "title": row["title"] or row["content"][:80],
                "agent_id": row["agent_id"],
                "status": row["status"],
                "created_at": row["created_at"],
            },
            "neighbors": neighbors,
        })
    except Exception as e:
        logger.error(f"Error getting note: {e}")
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
    """Log a turn and optionally add a summary note"""
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
        hint = manager.log_chat_to_planet("web", topic, message, agent_id, sender)
        result = {"status": "success", "logged": True}

        if summary:
            manager.add_note("web", topic, "summary", summary, agent_id=agent_id)
            result["summary"] = summary

        if hint:
            result["_suggest"] = hint

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in session turn: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/session/read/<topic>", methods=["GET"])
def session_read(topic):
    """Read planet details for a topic"""
    try:
        conn = get_db().connection
        mgr = get_session()
        slug = mgr.normalize_topic(topic)
        row = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (slug,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        notes = conn.execute(
            "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 50",
            (slug,),
        ).fetchall()
        data = _planet_to_json(dict(row), [dict(n) for n in notes])
        lines = [f"# Planet: {data['display_topic']}"]
        if data["goal"]: lines.append(f"\nGoal: {data['goal']}")
        if data["current_state"]: lines.append(f"\nState: {data['current_state']}")
        if data["next_steps"]:
            lines.append("\nNext steps:")
            lines.extend(f"  - {s}" for s in data["next_steps"])
        if data["notes"]:
            lines.append(f"\nNotes ({len(data['notes'])}):")
            for n in data["notes"]:
                lines.append(f"\n[{n['kind'].upper()}] {n['content']}")
        return jsonify({"topic": slug, "content": "\n".join(lines)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Planet/Note API (unified planets/notes tables) ──────────

def _safe_json(val, fallback=None):
    if not val or not val.strip():
        return fallback or []
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return fallback or []


def _planet_to_json(row: dict, notes: list = None):
    return {
        "topic": row["topic"],
        "display_topic": row.get("display_topic") or row["topic"],
        "status": row.get("status", "active"),
        "goal": row.get("goal", ""),
        "current_state": row.get("current_state", ""),
        "next_step": row.get("next_step", ""),
        "next_steps": _safe_json(row.get("next_steps")),
        "files": _safe_json(row.get("files")),
        "commands": _safe_json(row.get("commands")),
        "handoff": row.get("handoff", ""),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
        "notes": [
            {
                "id": n.get("id"),
                "kind": n.get("kind"),
                "content": n.get("content"),
                "title": n.get("title") or n.get("content", "")[:80],
                "agent_id": n.get("agent_id", "default"),
                "status": n.get("status", "open"),
                "created_at": n.get("created_at", ""),
            }
            for n in (notes or [])
        ] if notes else [],
    }


@app.route("/api/planets", methods=["GET"])
def api_list_planets():
    try:
        conn = get_db().connection
        rows = conn.execute(
            "SELECT * FROM planets ORDER BY updated_at DESC"
        ).fetchall()
        return jsonify({
            "planets": [_planet_to_json(dict(r)) for r in rows]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/planets/<topic>", methods=["GET"])
def api_get_planet(topic):
    try:
        conn = get_db().connection
        row = conn.execute(
            "SELECT * FROM planets WHERE topic = ?", (topic,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Planet not found"}), 404
        notes = conn.execute(
            "SELECT * FROM notes WHERE topic = ? ORDER BY created_at DESC LIMIT 50",
            (topic,),
        ).fetchall()
        return jsonify(_planet_to_json(dict(row), [dict(n) for n in notes]))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/planets", methods=["POST"])
def api_upsert_planet():
    try:
        data = request.get_json()
        raw_topic = data.get("topic", "").strip()
        if not raw_topic:
            return jsonify({"error": "topic required"}), 400

        mgr = get_session()
        mgr.update_planet(
            "web",
            raw_topic,
            status=data.get("status"),
            goal=data.get("goal"),
            current_state=data.get("current_state"),
            next_step=data.get("next_step"),
            handoff=data.get("handoff"),
        )
        return jsonify({"status": "success", "topic": topic})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/planets/<topic>", methods=["DELETE"])
def api_delete_planet(topic):
    try:
        mgr = get_session()
        mgr.delete_planet(topic)
        return jsonify({"status": "success", "deleted": topic})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notes", methods=["POST"])
def api_add_note():
    try:
        data = request.get_json()
        raw_topic = data.get("topic", "").strip()
        kind = data.get("kind", "fact")
        content = data.get("content", "")
        if not raw_topic or not content:
            return jsonify({"error": "topic and content required"}), 400

        mgr = get_session()
        result = mgr.add_note(
            "web", raw_topic, kind, content,
            agent_id=data.get("agent_id", "web-ui"),
            title=data.get("title"),
        )
        return jsonify({"status": "success", "note": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_note_color(kind: str) -> str:
    colors = {
        "decision": "#8aa2ff",
        "fact": "#2196F3",
        "issue": "#f44336",
        "question": "#FFC107",
        "summary": "#f97316",
        "turn": "#06b6d4",
        "concept": "#7c3aed",
        "example": "#00BCD4",
    }
    return colors.get(kind, "#757575")


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
