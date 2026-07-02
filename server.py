"""Web server for BaseMem visualization and API"""

import json
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from storage.db import StorageManager
from storage.sessions import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

_storage = None


def _db_path():
    return str(Path.home() / ".basemem" / "basemem.db")


def get_session() -> SessionManager:
    global _storage
    if _storage is None:
        _storage = StorageManager(_db_path())
    return SessionManager(_storage)


@app.route("/", methods=["GET"])
def index():
    """BaseMem API server."""
    return jsonify({
        "service": "BaseMem",
        "version": "0.2.0",
        "endpoints": {
            "planets": "/api/planets",
            "notes": "/api/notes",
            "notes_graph": "/api/notes/graph",
            "search": "/api/search?q=...",
            "code_search": "/api/code/search?q=...",
            "code_status": "/api/code/status",
            "graph": "/api/graph",
        }
    })


def _build_notes_graph(planet_filter: str = ""):
    """Build D3 graph data from notes/links for a single planet or all planets."""
    mgr = get_session()
    nodes = []
    edges = []

    planets = mgr.list_planets()
    if planet_filter:
        p = mgr.get_planet_dict(planet_filter)
        planets = [p] if p else []

    for p in planets:
        slug = p["topic"]
        pid = f"planet-{slug}"
        nodes.append({
            "id": pid, "title": p.get("display_topic") or slug,
            "type": "planet", "group": 0, "weight": 2,
            "color": "#f97316",
        })

        note_rows = mgr.get_notes_for_planet(slug, limit=50)

        for n in note_rows:
            nid = f"note-{n['id']}"
            label = n.get("title") or n.get("content", "")[:60]
            nodes.append({
                "id": nid, "title": label, "type": n.get("kind"),
                "group": slug, "weight": 1,
                "color": _get_note_color(n.get("kind", "")),
                "planet": slug,
            })
            edges.append({
                "source": pid, "target": nid,
                "type": "contains", "weight": 0.5,
            })

        links = mgr.get_note_links_for_planet(slug)

        for link in links:
            edges.append({
                "source": f"note-{link['from_note_id']}",
                "target": f"note-{link['to_note_id']}",
                "type": link["link_type"],
                "weight": link.get("weight") or 1,
                "confidence": link.get("confidence") or 1,
                "link_source": link.get("source") or "auto",
            })

    if not planet_filter:
        plinks = mgr.get_all_planet_links()
        for pl in plinks:
            edges.append({
                "source": f"planet-{pl['from_topic']}",
                "target": f"planet-{pl['to_topic']}",
                "type": "planet_link",
                "weight": pl.get("weight") or 1,
                "confidence": 1.0,
                "relation": pl["relation"],
            })

    return jsonify({"nodes": nodes, "edges": edges, "stats": {"planets": len(planets), "notes": len(nodes) - len(planets)}})


@app.route("/api/graph/<project_id>", methods=["GET"])
def project_graph_data(project_id):
    """Get graph data for a specific project (notes + note_links)."""
    try:
        return _build_notes_graph(project_id)
    except Exception as e:
        logger.error(f"Error getting project graph: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/notes/graph", methods=["GET"])
def notes_graph():
    """Get all notes + links as D3 graph data, grouped by planet."""
    try:
        return _build_notes_graph()
    except Exception as e:
        logger.error(f"Error getting notes graph: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/notes/<int:note_id>", methods=["GET"])
def get_note_detail(note_id):
    """Get a single note with its linked neighbors."""
    try:
        mgr = get_session()
        row = mgr.get_note(note_id)
        if not row:
            return jsonify({"error": "Note not found"}), 404

        neighbors = mgr.get_note_neighbors(note_id)

        return jsonify({
            "note": {
                "id": f"note-{row['id']}",
                "topic": row["topic"],
                "kind": row["kind"],
                "content": row["content"],
                "title": row.get("title") or row["content"][:80],
                "agent_id": row.get("agent_id"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
            },
            "neighbors": neighbors,
        })
    except Exception as e:
        logger.error(f"Error getting note: {e}")
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

        manager = get_session()
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
        mgr = get_session()
        data = mgr.get_planet_with_notes(topic)
        if not data:
            return jsonify({"error": "Not found"}), 404
        lines = [f"# Planet: {data.get('display_topic') or data['topic']}"]
        if data.get("goal"):
            lines.append(f"\nGoal: {data['goal']}")
        if data.get("current_state"):
            lines.append(f"\nState: {data['current_state']}")
        if data.get("next_steps"):
            lines.append("\nNext steps:")
            lines.extend(f"  - {s}" for s in _safe_json(data["next_steps"]))
        notes = data.get("notes", [])
        if notes:
            lines.append(f"\nNotes ({len(notes)}):")
            for n in notes:
                lines.append(f"\n[{n['kind'].upper()}] {n.get('content', '')}")
        return jsonify({"topic": data["topic"], "content": "\n".join(lines)})
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


def _planet_to_json(row: dict, notes: list | None = None):
    return {
        "topic": row["topic"],
        "display_topic": row.get("display_topic") or row["topic"],
        "status": row.get("status", "active"),
        "memory_state": row.get("memory_state", "hot"),
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
        mgr = get_session()
        rows = mgr.list_planets()
        return jsonify({
            "planets": [_planet_to_json(r) for r in rows]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/planets/<topic>", methods=["GET"])
def api_get_planet(topic):
    try:
        mgr = get_session()
        data = mgr.get_planet_with_notes(topic)
        if not data:
            return jsonify({"error": "Planet not found"}), 404
        return jsonify(_planet_to_json(data, data.get("notes", [])))
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
        return jsonify({"status": "success", "topic": raw_topic})
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


@app.route("/api/planet-links", methods=["POST"])
def api_link_planets():
    """Create a link between two planets."""
    try:
        data = request.get_json()
        mgr = get_session()
        ok, msg = mgr.link_planets(
            data.get("from_planet", ""),
            data.get("to_planet", ""),
            data.get("relation", "related"),
            data.get("weight", 1.0),
        )
        if ok:
            return jsonify({"status": "success", "message": msg})
        return jsonify({"error": msg}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/planet-links/<topic>", methods=["GET"])
def api_get_planet_links(topic):
    """Get all links for a planet."""
    try:
        mgr = get_session()
        links = mgr.get_planet_links(topic)
        return jsonify({"planet": topic, "links": links})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recompute-links", methods=["POST"])
def api_recompute_links():
    """Recompute Jaccard similarity for all note pairs."""
    try:
        data = request.get_json() or {}
        mgr = get_session()
        result = mgr.recompute_links(
            topic=data.get("topic"),
            threshold=data.get("threshold", 0.1),
            min_weight=data.get("min_weight", 0.05),
        )
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search")
def api_search():
    """Search across planets and notes."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    mgr = get_session()
    results = []
    all_results = mgr.search_all(q, limit=20)
    for r in all_results.get("planets", []):
        label = r.get("display_topic") or r["topic"]
        results.append({
            "type": "planet", "label": label, "id": "planet-" + r["topic"],
            "preview": (r.get("current_state") or r.get("goal") or "")[:150],
        })
    for r in all_results.get("notes", []):
        results.append({
            "type": "note", "label": f"{r['topic']} / {r['kind']}", "id": f"note-{r['id']}",
            "preview": r.get("content", "")[:150], "topic": r["topic"],
        })
    return jsonify({"results": results})


@app.route("/api/edge/decay", methods=["POST"])
def api_edge_decay():
    """Apply weight decay to auto-links."""
    try:
        data = request.get_json() or {}
        mgr = get_session()
        result = mgr.edge_decay(factor=data.get("factor", 0.9), planet=data.get("planet"))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/edge/prune", methods=["POST"])
def api_edge_prune():
    """Remove auto-links below a weight threshold."""
    try:
        data = request.get_json() or {}
        mgr = get_session()
        result = mgr.edge_prune(threshold=data.get("threshold", 0.05), planet=data.get("planet"))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export", methods=["GET"])
def api_export():
    """Export knowledge base as JSON."""
    try:
        planet = request.args.get("planet")
        mgr = get_session()
        data = mgr.export_kb(planet=planet)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/import", methods=["POST"])
def api_import():
    """Import knowledge base from JSON."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "request body required"}), 400
        mgr = get_session()
        stats = mgr.import_kb(data)
        return jsonify({"status": "success", "result": stats})
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


# ── Code Graph API ────────────────────────────────────────────────


@app.route("/api/code/init", methods=["POST"])
def code_init():
    """Index a project's source code into a per-project .basemem.code.db."""
    data = request.get_json(silent=True) or {}
    root = data.get("root_path", "")
    if not root or not os.path.isdir(root):
        return jsonify({"error": "Invalid root_path"}), 400
    from indexer import CodeIndexer
    indexer = CodeIndexer(root)
    try:
        result = indexer.index_project()
        return jsonify({**result, "db_path": indexer.db_path})
    finally:
        indexer.close()


@app.route("/api/code/search", methods=["GET"])
def code_search():
    """Search code symbols in a project's .basemem.code.db."""
    root = request.args.get("root", "")
    query = request.args.get("q", "")
    if not root or not os.path.isdir(root):
        return jsonify({"error": "Missing or invalid root param"}), 400
    if not query:
        return jsonify({"error": "Missing query"}), 400
    limit = int(request.args.get("limit", 20))
    use_regex = request.args.get("regex", "").lower() in ("true", "1", "yes")
    from indexer import CodeIndexer
    from indexer.indexer import CODE_DB_FILENAME
    db_path = os.path.join(root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return jsonify({"error": f"No index at {db_path}"}), 404
    indexer = CodeIndexer(root)
    try:
        results = indexer.search_symbols(query, limit=limit, use_regex=use_regex)
        return jsonify(results)
    finally:
        indexer.close()


@app.route("/api/code/symbol/<int:symbol_id>", methods=["GET"])
def code_symbol(symbol_id: int):
    """Get a code symbol by ID from a project's .basemem.code.db."""
    root = request.args.get("root", "")
    if not root or not os.path.isdir(root):
        return jsonify({"error": "Missing or invalid root param"}), 400
    from indexer import CodeIndexer
    from indexer.indexer import CODE_DB_FILENAME
    db_path = os.path.join(root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return jsonify({"error": f"No index at {db_path}"}), 404
    indexer = CodeIndexer(root)
    try:
        sym = indexer.get_symbol(symbol_id)
        if not sym:
            return jsonify({"error": "Not found"}), 404
        callers = indexer.get_callers(sym["symbol_name"])
        callees = indexer.get_callees(sym["symbol_name"], sym["file_path"])
        return jsonify({"symbol": sym, "callers": callers, "callees": callees})
    finally:
        indexer.close()


@app.route("/api/code/status", methods=["GET"])
def code_status():
    """Code graph indexing status for a project."""
    root = request.args.get("root", "")
    if not root or not os.path.isdir(root):
        return jsonify({"error": "Missing or invalid root param"}), 400
    from indexer import CodeIndexer
    from indexer.indexer import CODE_DB_FILENAME
    db_path = os.path.join(root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        return jsonify({"error": f"No index at {db_path}"}), 404
    indexer = CodeIndexer(root)
    try:
        return jsonify(indexer.get_project_stats())
    finally:
        indexer.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
