"""Tests for all 30 MCP tools (memory + graph + code tool smoke tests)."""

import os
import json
import tempfile
from pathlib import Path
import pytest

from storage.db import StorageManager
from storage.sessions import SessionManager

try:
    import tree_sitter  # noqa: F401
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


@pytest.fixture
def temp_db():
    """Create a temp DB and return its path + a SessionManager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        # Point BASEMEM_DB_PATH so MCP tools use this DB
        old_env = os.environ.get("BASEMEM_DB_PATH")
        os.environ["BASEMEM_DB_PATH"] = str(db_path)
        storage = StorageManager(str(db_path))
        manager = SessionManager(storage)
        yield db_path, storage, manager
        storage.close()
        if old_env is None:
            del os.environ["BASEMEM_DB_PATH"]
        else:
            os.environ["BASEMEM_DB_PATH"] = old_env


@pytest.fixture
def seeded_db(temp_db):
    """Seed a DB with a planet, notes, and links for graph tests."""
    db_path, storage, manager = temp_db

    # Create planet
    manager.update_planet("test", "graph-test-planet",
                          current_state="testing graph tools",
                          next_step="test all tools",
                          status="active",
                          goal="no bugs")

    # Add notes
    n1 = manager.add_note("test", "graph-test-planet", "fact", "First note about graphs")
    n2 = manager.add_note("test", "graph-test-planet", "fact", "Second note about edges")
    n3 = manager.add_note("test", "graph-test-planet", "decision", "Use weighted graphs")
    n4 = manager.add_note("test", "graph-test-planet", "issue", "Need better pruning")

    # Link notes for graph tools
    manager.link_notes(n1["id"], n2["id"], "related", 0.8)
    manager.link_notes(n1["id"], n3["id"], "related", 0.5)
    manager.link_notes(n2["id"], n3["id"], "related", 0.3)
    manager.link_notes(n3["id"], n4["id"], "related", 0.9)

    return db_path, storage, manager


# ═══════════════════════════════════════════════════════════
# Planet / Note CRUD
# ═══════════════════════════════════════════════════════════

class TestPlanetTools:
    def test_update_planet(self, temp_db):
        from mcp_server.server import update_planet
        db_path, storage, manager = temp_db
        r = update_planet(topic="my-project", currentState="in progress", nextStep="write tests")
        assert "updated" in r.lower()
        p = manager.get_planet("my-project")
        assert p is not None
        assert "in progress" in p.metadata["current_state"]

    def test_read_planet(self, temp_db):
        from mcp_server.server import read_planet
        db_path, storage, manager = temp_db
        manager.update_planet("test", "read-test", current_state="ready")
        r = read_planet(topic="read-test")
        assert "read-test" in r or "Read-Test" in r
        assert "ready" in r

    def test_read_planet_not_found(self, temp_db):
        from mcp_server.server import read_planet
        r = read_planet(topic="nonexistent")
        assert "No planet found" in r

    def test_list_planets(self, temp_db):
        from mcp_server.server import list_planets
        db_path, storage, manager = temp_db
        manager.update_planet("test", "alpha", current_state="ok")
        manager.update_planet("test", "beta", current_state="ok")
        r = list_planets()
        assert "alpha" in r
        assert "beta" in r

    def test_list_planets_empty(self, temp_db):
        from mcp_server.server import list_planets
        r = list_planets()
        assert "No planets" in r

    def test_getContext_existing(self, temp_db):
        from mcp_server.server import getContext
        db_path, storage, manager = temp_db
        manager.update_planet("test", "ctx-test", current_state="alive", next_step="grow")
        manager.add_note("test", "ctx-test", "decision", "go fast")
        r = getContext(topic="ctx-test")
        assert "ctx:" in r
        assert "alive" in r
        assert "go fast" in r

    def test_getContext_unknown(self, temp_db):
        from mcp_server.server import getContext
        r = getContext(topic="nonexistent")
        assert "ctx:" in r
        assert "no context" in r


class TestNoteTools:
    def test_log_interaction(self, temp_db):
        from mcp_server.server import log_interaction
        db_path, storage, manager = temp_db
        r = log_interaction(topic="log-test", decision="use pytest",
                            fact="tests pass", currentState="done")
        assert "note(decision)" in r
        assert "note(fact)" in r
        assert "planet_updated" in r

    def test_log_interaction_summary(self, temp_db):
        from mcp_server.server import log_interaction
        r = log_interaction(topic="log-test", summary="All done.")
        assert "note(summary)" in r

    def test_log_interaction_activity(self, temp_db):
        from mcp_server.server import log_interaction
        r = log_interaction(topic="log-test", activity="working")
        assert "turn_logged" in r

    def test_log_interaction_noop(self, temp_db):
        from mcp_server.server import log_interaction
        r = log_interaction(topic="log-test")
        assert "no changes" in r

    def test_search_notes(self, temp_db):
        from mcp_server.server import search_notes
        db_path, storage, manager = temp_db
        manager.add_note("test", "search-test", "fact", "find me")
        r = search_notes(topic="search-test")
        assert "find me" in r

    def test_search_notes_empty(self, temp_db):
        from mcp_server.server import search_notes
        r = search_notes(topic="nope")
        assert "No matching" in r

    def test_search_notes_kind_filter(self, temp_db):
        from mcp_server.server import search_notes
        db_path, storage, manager = temp_db
        manager.add_note("test", "sfilter", "decision", "only this one")
        manager.add_note("test", "sfilter", "fact", "not this")
        r = search_notes(topic="sfilter", kind="decision")
        assert "only this one" in r
        assert "not this" not in r

    def test_search_notes_query_filter(self, temp_db):
        from mcp_server.server import search_notes
        db_path, storage, manager = temp_db
        manager.add_note("test", "sq", "fact", "apple pie")
        manager.add_note("test", "sq", "fact", "banana split")
        r = search_notes(topic="sq", query="apple")
        assert "apple pie" in r
        assert "banana" not in r

    def test_get_node(self, temp_db):
        from mcp_server.server import get_node
        db_path, storage, manager = temp_db
        note = manager.add_note("test", "node-test", "fact", "hello node")
        nid = note["id"]
        r = get_node(nodeId=nid)
        assert "hello node" in r

    def test_get_node_not_found(self, temp_db):
        from mcp_server.server import get_node
        r = get_node(nodeId="note-99999")
        assert "No node found" in r

    def test_get_node_invalid_id(self, temp_db):
        from mcp_server.server import get_node
        r = get_node(nodeId="not-a-note")
        assert "Invalid" in r or "not found" in r.lower()

    def test_search_nodes(self, temp_db):
        from mcp_server.server import search_nodes
        db_path, storage, manager = temp_db
        manager.add_note("test", "sn-test", "fact", "unique rabbit hole")
        r = search_nodes(query="rabbit")
        assert "rabbit" in r

    def test_search_nodes_empty(self, temp_db):
        from mcp_server.server import search_nodes
        r = search_nodes(query="zzzzzzzzz")
        assert "No matches" in r or "no matches" in r.lower()

    def test_summarize_planet(self, temp_db):
        from mcp_server.server import summarize_planet
        db_path, storage, manager = temp_db
        manager.add_note("test", "sum-test", "decision", "key insight")
        r = summarize_planet(topic="sum-test")
        assert "key insight" in r

    def test_summarize_planet_not_found(self, temp_db):
        from mcp_server.server import summarize_planet
        r = summarize_planet(topic="no-such-planet")
        assert "No planet found" in r

    def test_compact_planet(self, temp_db):
        from mcp_server.server import compact_planet
        db_path, storage, manager = temp_db
        for i in range(5):
            manager.add_note("test", "compact-test", "fact", f"note {i}")
        r = compact_planet(topic="compact-test")
        assert "Compacted" in r


# ═══════════════════════════════════════════════════════════
# Note / Planet Links
# ═══════════════════════════════════════════════════════════

class TestLinkTools:
    def test_link_notes(self, temp_db):
        from mcp_server.server import link_notes
        db_path, storage, manager = temp_db
        n1 = manager.add_note("test", "link-test", "fact", "node A")
        n2 = manager.add_note("test", "link-test", "fact", "node B")
        r = link_notes(fromNoteId=n1["id"], toNoteId=n2["id"], linkType="related", weight=0.9)
        assert "Linked" in r

    def test_link_notes_invalid(self, temp_db):
        from mcp_server.server import link_notes
        r = link_notes(fromNoteId="note-999", toNoteId="note-888")
        assert "Linked" in r or "Invalid" in r

    def test_link_notes_self(self, temp_db):
        from mcp_server.server import link_notes
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "self-test", "fact", "alone")
        r = link_notes(fromNoteId=n["id"], toNoteId=n["id"])
        assert "itself" in r

    def test_get_note_neighbors(self, seeded_db):
        from mcp_server.server import get_note_neighbors
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_note_neighbors(noteId=f"note-{nid}")
        assert "Neighbors" in r
        assert "note-" in r

    def test_get_note_neighbors_empty(self, temp_db):
        from mcp_server.server import get_note_neighbors
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "isolated", "fact", "lonely")
        r = get_note_neighbors(noteId=n["id"])
        assert "No linked" in r

    def test_link_planets(self, temp_db):
        from mcp_server.server import link_planets
        db_path, storage, manager = temp_db
        manager.update_planet("test", "planet-a", current_state="a")
        manager.update_planet("test", "planet-b", current_state="b")
        r = link_planets(fromPlanet="planet-a", toPlanet="planet-b", relation="related", weight=1.0)
        assert "Linked" in r

    def test_link_planets_missing(self, temp_db):
        from mcp_server.server import link_planets
        r = link_planets(fromPlanet="real", toPlanet="ghost")
        assert "not found" in r.lower()

    def test_get_planet_links(self, temp_db):
        from mcp_server.server import get_planet_links
        db_path, storage, manager = temp_db
        manager.update_planet("test", "alpha", current_state="x")
        manager.update_planet("test", "beta", current_state="y")
        manager.link_planets("alpha", "beta", "related", 1.0)
        r = get_planet_links(planet="alpha")
        assert "beta" in r or "alpha" in r

    def test_get_planet_links_empty(self, temp_db):
        from mcp_server.server import get_planet_links
        manager = temp_db[2]
        manager.update_planet("test", "lonely", current_state="x")
        r = get_planet_links(planet="lonely")
        assert "No planet links" in r

    def test_set_memory_state(self, temp_db):
        from mcp_server.server import set_memory_state
        db_path, storage, manager = temp_db
        manager.update_planet("test", "mem-test", current_state="ok")
        r = set_memory_state(topic="mem-test", state="warm")
        assert "warm" in r

    def test_set_memory_state_invalid(self, temp_db):
        from mcp_server.server import set_memory_state
        r = set_memory_state(topic="any", state="invalid")
        assert "must be" in r.lower()


# ═══════════════════════════════════════════════════════════
# Graph traversal tools
# ═══════════════════════════════════════════════════════════

class TestGraphTools:
    def test_get_neighbors_weighted(self, seeded_db):
        from mcp_server.server import get_neighbors_weighted
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_neighbors_weighted(noteId=f"note-{nid}", depth=2, minWeight=0.0)
        assert "Neighbors" in r
        assert len(r.splitlines()) > 1

    def test_get_neighbors_weighted_min_weight(self, seeded_db):
        from mcp_server.server import get_neighbors_weighted
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_neighbors_weighted(noteId=f"note-{nid}", depth=1, minWeight=0.9)
        if "No neighbors" in r:
            assert True  # no edge >= 0.9
        else:
            assert "Neighbors" in r

    def test_get_neighbors_weighted_no_links(self, temp_db):
        from mcp_server.server import get_neighbors_weighted
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = get_neighbors_weighted(noteId=n["id"])
        assert "No neighbors" in r

    def test_get_neighbors_weighted_invalid_id(self, seeded_db):
        from mcp_server.server import get_neighbors_weighted
        r = get_neighbors_weighted(noteId="note-99999")
        assert "No neighbors" in r or "Invalid" in r

    def test_get_subgraph(self, seeded_db):
        from mcp_server.server import get_subgraph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_subgraph(noteId=f"note-{nid}", depth=2, minWeight=0.0)
        data = json.loads(r)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 2  # at least self + 1 neighbor

    def test_get_subgraph_deep(self, seeded_db):
        from mcp_server.server import get_subgraph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_subgraph(noteId=f"note-{nid}", depth=3, minWeight=0.0)
        data = json.loads(r)
        assert len(data["nodes"]) >= 2
        assert len(data["edges"]) >= 1

    def test_get_subgraph_no_links(self, temp_db):
        from mcp_server.server import get_subgraph
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = get_subgraph(noteId=n["id"])
        data = json.loads(r)
        assert "nodes" in data
        assert len(data["nodes"]) >= 1  # self is always included
        assert len(data["edges"]) == 0

    def test_get_subgraph_invalid_id(self, seeded_db):
        from mcp_server.server import get_subgraph
        r = get_subgraph(noteId="note-99999")
        data = json.loads(r)
        assert data["nodes"] == []

    def test_rank_neighbors(self, seeded_db):
        from mcp_server.server import rank_neighbors
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = rank_neighbors(noteId=f"note-{nid}", by="weight")
        assert "ranked" in r.lower()

    def test_rank_neighbors_no_links(self, temp_db):
        from mcp_server.server import rank_neighbors
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = rank_neighbors(noteId=n["id"])
        assert "No neighbors" in r

    def test_rank_neighbors_by_confidence(self, seeded_db):
        from mcp_server.server import rank_neighbors
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = rank_neighbors(noteId=f"note-{nid}", by="confidence")
        assert "ranked" in r.lower()

    def test_compute_similarity(self, seeded_db):
        from mcp_server.server import compute_similarity
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        if len(notes) >= 2:
            r = compute_similarity(noteIdA=f"note-{notes[0]['id']}",
                                   noteIdB=f"note-{notes[1]['id']}")
            assert notes[0]["kind"] in r.lower() or notes[0]["kind"] in r
            assert "Agent:" in r

    def test_compute_similarity_one_invalid(self, seeded_db):
        from mcp_server.server import compute_similarity
        notes = seeded_db[2].search_notes("graph-test-planet")
        nid = notes[0]["id"] if notes else 1
        r = compute_similarity(noteIdA=f"note-{nid}", noteIdB="note-99999")
        assert "not found" in r.lower() or "Invalid" in r

    def test_compute_similarity_not_found(self, temp_db):
        from mcp_server.server import compute_similarity
        r = compute_similarity(noteIdA="note-99991", noteIdB="note-99992")
        assert "not found" in r.lower() or "Invalid" in r

    def test_rerank(self, seeded_db):
        from mcp_server.server import rerank
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        ids = [f"note-{n['id']}" for n in notes]
        r = rerank(query="graph", noteIds=ids)
        assert "Query: graph" in r
        assert "Candidate notes" in r

    def test_rerank_empty_ids(self, seeded_db):
        from mcp_server.server import rerank
        r = rerank(query="test", noteIds=[])
        assert "No valid" in r

    def test_rerank_invalid_ids(self, seeded_db):
        from mcp_server.server import rerank
        r = rerank(query="test", noteIds=["note-bogus"])
        assert "No valid" in r

    def test_edge_decay(self, seeded_db):
        from mcp_server.server import edge_decay
        r = edge_decay(factor=0.5)
        assert "Decayed" in r
        # verify weights decreased
        nid = _first_note_id(seeded_db)
        before = _neighbor_weights(seeded_db, nid)
        r2 = edge_decay(factor=0.5)
        after = _neighbor_weights(seeded_db, nid)
        if before:
            assert all(a <= b for a, b in zip(after, before))

    def test_edge_decay_by_planet(self, seeded_db):
        from mcp_server.server import edge_decay
        r = edge_decay(factor=0.9, planet="graph-test-planet")
        assert "Decayed" in r

    def test_edge_decay_invalid_planet(self, temp_db):
        from mcp_server.server import edge_decay
        r = edge_decay(factor=0.9, planet="nonexistent")
        assert "Decayed" in r  # 0 edges decayed

    def test_edge_prune(self, seeded_db):
        from mcp_server.server import edge_prune
        # First create a very low-weight edge
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        if len(notes) >= 2:
            manager.link_notes(f"note-{notes[0]['id']}", f"note-{notes[1]['id']}", "related", 0.01)
        r = edge_prune(threshold=0.05)
        assert "Pruned" in r

    def test_edge_prune_by_planet(self, seeded_db):
        from mcp_server.server import edge_prune
        r = edge_prune(threshold=0.05, planet="graph-test-planet")
        assert "Pruned" in r

    def test_edge_prune_invalid_planet(self, temp_db):
        from mcp_server.server import edge_prune
        r = edge_prune(threshold=0.05, planet="nonexistent")
        assert "Pruned" in r  # 0 edges pruned


# ═══════════════════════════════════════════════════════════
# Code tools — smoke tests (error handling / edge cases)
# ═══════════════════════════════════════════════════════════

pytestmark_code = pytest.mark.skipif(not HAS_TREE_SITTER, reason="tree_sitter not installed")

class TestCodeTools:
    def test_code_init_nonexistent(self):
        """code_init checks directory before importing indexer, so it works without tree_sitter."""
        from mcp_server.server import code_init
        r = code_init(projectRoot="/tmp/__nonexistent_project_path__")
        assert "not found" in r.lower() or "Directory" in r

    @pytestmark_code
    def test_code_find_no_project(self):
        from mcp_server.server import code_find
        r = code_find(projectRoot="/tmp/__nonexistent__")
        assert "not found" in r.lower() or "No code index" in r

    def test_code_find_grep_no_rg(self):
        """grep mode returns before indexer import, so it works without tree_sitter."""
        from mcp_server.server import code_find
        r = code_find(query="test", grep=True, projectRoot="/tmp")
        assert isinstance(r, str)

    @pytestmark_code
    def test_code_trace_no_index(self):
        from mcp_server.server import code_trace
        r = code_trace("main", projectRoot="/tmp/__nonexistent__")
        assert "No code index" in r

    @pytestmark_code
    def test_code_files_no_index(self):
        from mcp_server.server import code_files
        r = code_files(projectRoot="/tmp/__nonexistent__")
        assert "No code index" in r

    def test_code_files_glob(self, tmp_path):
        """glob mode returns before indexer import, so it works without tree_sitter."""
        from mcp_server.server import code_files
        d = tmp_path / "globtest"
        d.mkdir()
        (d / "a.json").write_text("{}")
        (d / "b.txt").write_text("x")
        r = code_files(projectRoot=str(d), pattern="**/*.json")
        assert "a.json" in r

    def test_code_files_glob_no_match(self, tmp_path):
        from mcp_server.server import code_files
        r = code_files(projectRoot=str(tmp_path), pattern="**/*.nosuch")
        assert "No files matching" in r

    @pytestmark_code
    def test_code_explore_no_index(self):
        from mcp_server.server import code_explore
        r = code_explore("main", projectRoot="/tmp/__nonexistent__")
        assert "No code index" in r

    @pytestmark_code
    def test_code_impact_no_index(self):
        from mcp_server.server import code_impact
        r = code_impact("main", projectRoot="/tmp/__nonexistent__")
        assert "No code index" in r

    @pytestmark_code
    def test_code_read_no_index(self):
        from mcp_server.server import code_read
        r = code_read("main.py", projectRoot="/tmp/__nonexistent__")
        assert "No code index" in r

    @pytestmark_code
    def test_code_list_projects(self):
        from mcp_server.server import code_list_projects
        r = code_list_projects()
        assert isinstance(r, str)

    @pytestmark_code
    def test_code_read_traversal_blocked(self, tmp_path):
        from mcp_server.server import code_read
        d = tmp_path / "safe"
        d.mkdir()
        (d / "f.py").write_text("x")
        r = code_read("../etc/passwd", projectRoot=str(d))
        assert "outside" in r.lower()


def _first_note_id(seeded_db):
    """Helper: get first note id in the seeded planet."""
    _, storage, manager = seeded_db
    notes = manager.search_notes("graph-test-planet")
    return notes[0]["id"] if notes else 1


def _neighbor_weights(seeded_db, note_id):
    """Helper: get neighbor weights for a note."""
    _, storage, manager = seeded_db
    return [nb["weight"] for nb in manager.get_note_neighbors(note_id)]
