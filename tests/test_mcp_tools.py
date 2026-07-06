"""Tests for all 35 core MCP tools (memory + graph + code + sessions + tasks smoke tests)."""

import json
import os
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
    def test_logInteraction(self, temp_db):
        from mcp_server.server import logInteraction
        db_path, storage, manager = temp_db
        r = logInteraction(topic="log-test", decision="use pytest",
                            fact="tests pass", currentState="done")
        assert "note(decision)" in r
        assert "note(fact)" in r
        assert "planet_updated" in r

    def test_logInteraction_summary(self, temp_db):
        from mcp_server.server import logInteraction
        r = logInteraction(topic="log-test", summary="All done.")
        assert "note(summary)" in r

    def test_logInteraction_activity(self, temp_db):
        from mcp_server.server import logInteraction
        r = logInteraction(topic="log-test", activity="working")
        assert "turn_logged" in r

    def test_logInteraction_noop(self, temp_db):
        from mcp_server.server import logInteraction
        r = logInteraction(topic="log-test")
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

    def test_read_planet_with_limit(self, temp_db):
        from mcp_server.server import read_planet
        db_path, storage, manager = temp_db
        manager.add_note("test", "sum-test", "decision", "key insight")
        r = read_planet(topic="sum-test", limit=50)
        assert "key insight" in r

    def test_read_planet_not_found(self, temp_db):
        from mcp_server.server import read_planet
        r = read_planet(topic="no-such-planet")
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
        from mcp_server.server import link
        db_path, storage, manager = temp_db
        n1 = manager.add_note("test", "link-test", "fact", "node A")
        n2 = manager.add_note("test", "link-test", "fact", "node B")
        r = link(fromId=n1["id"], toId=n2["id"], linkType="related", weight=0.9, kind="notes")
        assert "Linked" in r

    def test_link_notes_invalid(self, temp_db):
        from mcp_server.server import link
        r = link(fromId="note-999", toId="note-888", kind="notes")
        assert "Linked" in r or "Invalid" in r

    def test_link_notes_self(self, temp_db):
        from mcp_server.server import link
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "self-test", "fact", "alone")
        r = link(fromId=n["id"], toId=n["id"], kind="notes")
        assert "itself" in r

    def test_get_graph_flat(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}")
        assert "Neighbors" in r
        assert "note-" in r

    def test_get_graph_flat_empty(self, temp_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "isolated", "fact", "lonely")
        r = get_graph(noteId=n["id"])
        assert "No neighbors" in r

    def test_link_planets(self, temp_db):
        from mcp_server.server import link
        db_path, storage, manager = temp_db
        manager.update_planet("test", "planet-a", current_state="a")
        manager.update_planet("test", "planet-b", current_state="b")
        r = link(fromId="planet-a", toId="planet-b", linkType="related", weight=1.0, kind="planets")
        assert "Linked" in r

    def test_link_planets_missing(self, temp_db):
        from mcp_server.server import link
        r = link(fromId="real", toId="ghost", kind="planets")
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
    def test_get_graph_flat_default(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}")
        assert "Neighbors" in r
        assert len(r.splitlines()) > 1

    def test_get_graph_flat_matches_storage_method(self, seeded_db):
        """get_graph depth=1 should return same notes as manager.get_note_neighbors."""
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        expected = {nb["id"] for nb in manager.get_note_neighbors(nid)}
        r = get_graph(noteId=f"note-{nid}")
        import re
        found = set()
        for m in re.finditer(r'note-(\d+)', r):
            found.add(int(m.group(1)))
        if expected:
            assert found == expected, f"Expected IDs {expected}, found {found}"

    def test_get_graph_min_weight(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", minWeight=0.9)
        if "No neighbors" in r:
            assert True
        else:
            assert "Neighbors" in r

    def test_get_graph_no_links(self, temp_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = get_graph(noteId=n["id"])
        assert "No neighbors" in r

    def test_get_graph_invalid_id(self, seeded_db):
        from mcp_server.server import get_graph
        r = get_graph(noteId="note-99999")
        assert "No neighbors" in r or "Invalid" in r

    def test_get_graph_subgraph(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", depth=2, minWeight=0.0)
        data = json.loads(r)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 2

    def test_get_graph_subgraph_deep(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", depth=3, minWeight=0.0)
        data = json.loads(r)
        assert len(data["nodes"]) >= 2
        assert len(data["edges"]) >= 1

    def test_get_graph_subgraph_no_links(self, temp_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = get_graph(noteId=n["id"], depth=2)
        data = json.loads(r)
        assert "nodes" in data
        assert len(data["nodes"]) >= 1
        assert len(data["edges"]) == 0

    def test_get_graph_subgraph_invalid_id(self, seeded_db):
        from mcp_server.server import get_graph
        r = get_graph(noteId="note-99999", depth=2)
        data = json.loads(r)
        assert data["nodes"] == []

    def test_get_graph_ranked(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", ranked=True)
        assert "ranked" in r.lower()

    def test_get_graph_ranked_sorted_by_weight_desc(self, seeded_db):
        """Ranked output must be sorted by weight descending."""
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", ranked=True)
        lines = r.strip().splitlines()
        weights = []
        for line in lines:
            import re
            m = re.search(r'w=([\d.]+)', line)
            if m:
                weights.append(float(m.group(1)))
        if weights:
            assert weights == sorted(weights, reverse=True), f"Expected descending weights, got {weights}"

    def test_get_graph_ranked_no_links(self, temp_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "alone", "fact", "solo")
        r = get_graph(noteId=n["id"], ranked=True)
        assert "No neighbors" in r

    def test_get_graph_ranked_min_weight(self, seeded_db):
        from mcp_server.server import get_graph
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        nid = notes[0]["id"]
        r = get_graph(noteId=f"note-{nid}", ranked=True, minWeight=0.9)
        if "No neighbors" in r:
            assert True
        else:
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

    def test_edge_maintain_decay(self, seeded_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(decayFactor=0.5)
        assert "Decayed" in r
        # verify weights decreased
        nid = _first_note_id(seeded_db)
        before = _neighbor_weights(seeded_db, nid)
        edge_maintain(decayFactor=0.5)
        after = _neighbor_weights(seeded_db, nid)
        if before:
            assert all(a <= b for a, b in zip(after, before, strict=False))

    def test_edge_maintain_decay_by_planet(self, seeded_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(decayFactor=0.9, planet="graph-test-planet")
        assert "Decayed" in r

    def test_edge_maintain_decay_invalid_planet(self, temp_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(decayFactor=0.9, planet="nonexistent")
        assert "Decayed" in r  # 0 edges decayed

    def test_edge_maintain_prune(self, seeded_db):
        from mcp_server.server import edge_maintain
        # First create a very low-weight edge
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        if len(notes) >= 2:
            manager.link_notes(f"note-{notes[0]['id']}", f"note-{notes[1]['id']}", "related", 0.01)
        r = edge_maintain(pruneThreshold=0.05)
        assert "Pruned" in r

    def test_edge_maintain_prune_by_planet(self, seeded_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(pruneThreshold=0.05, planet="graph-test-planet")
        assert "Pruned" in r

    def test_edge_maintain_prune_invalid_planet(self, temp_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(pruneThreshold=0.05, planet="nonexistent")
        assert "Pruned" in r  # 0 edges pruned

    def test_edge_maintain_both(self, seeded_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain(decayFactor=0.9, pruneThreshold=0.05)
        assert "Decayed" in r
        assert "Pruned" in r

    def test_edge_maintain_neither(self, seeded_db):
        from mcp_server.server import edge_maintain
        r = edge_maintain()
        assert "Error" in r


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


# ═══════════════════════════════════════════════════════════
# Note update tools
# ═══════════════════════════════════════════════════════════

class TestNoteUpdate:
    def _nid(self, manager, raw_id):
        """Parse note-{id} string to int."""
        return manager._parse_note_id(raw_id)

    def test_note_update_pin_only(self, temp_db):
        from mcp_server.server import note_update
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "nu-test", "fact", "test note")
        note_id_str = n["id"]
        r = note_update(noteId=note_id_str, pinned=True)
        assert "Pinned" in r
        row = manager.get_note(self._nid(manager, note_id_str))
        assert row["pinned"] == 1

    def test_note_update_unpin_only(self, temp_db):
        from mcp_server.server import note_update
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "nu-test", "fact", "test note")
        note_id_str = n["id"]
        manager.pin_note(note_id_str)
        r = note_update(noteId=note_id_str, pinned=False)
        assert "Unpinned" in r
        row = manager.get_note(self._nid(manager, note_id_str))
        assert row["pinned"] == 0

    def test_note_update_tags_only(self, temp_db):
        from mcp_server.server import note_update
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "nu-test", "fact", "test note")
        note_id_str = n["id"]
        r = note_update(noteId=note_id_str, tags="alpha, beta")
        assert "Tagged" in r
        row = manager.get_note(self._nid(manager, note_id_str))
        assert row["tags"] is not None
        import json as _json
        assert "alpha" in _json.loads(row["tags"])

    def test_note_update_neither(self, temp_db):
        from mcp_server.server import note_update
        r = note_update(noteId="note-1")
        assert "Error" in r

    def test_note_update_both(self, temp_db):
        from mcp_server.server import note_update
        db_path, storage, manager = temp_db
        n = manager.add_note("test", "nu-test", "fact", "test note")
        note_id_str = n["id"]
        r = note_update(noteId=note_id_str, pinned=True, tags="important")
        assert "Pinned" in r
        assert "Tagged" in r
        row = manager.get_note(self._nid(manager, note_id_str))
        assert row["pinned"] == 1
        import json as _json
        assert "important" in _json.loads(row["tags"])


# ═══════════════════════════════════════════════════════════
# Edge maintain combined operation
# ═══════════════════════════════════════════════════════════

class TestEdgeMaintainCombined:
    def test_edge_maintain_decay_then_prune_weights(self, seeded_db):
        from mcp_server.server import edge_maintain
        db_path, storage, manager = seeded_db
        notes = manager.search_notes("graph-test-planet")
        if len(notes) >= 2:
            # Add new notes to trigger auto-linking (auto-links are the ones
            # affected by edge_decay; manager.link_notes creates explicit links)
            n1 = manager.add_note("test", "graph-test-planet", "fact", "alpha test data")
            n2 = manager.add_note("test", "graph-test-planet", "fact", "alpha test experiment")
            nid = n1["id"]
            # Get auto-link weights before
            auto_before = _auto_neighbor_weights(manager, nid)
            r = edge_maintain(decayFactor=0.5, pruneThreshold=0.3)
            assert "Decayed" in r
            assert "Pruned" in r
            auto_after = _auto_neighbor_weights(manager, nid)
            # After decay by 0.5, remaining auto weights should be <= before * 0.5
            if auto_before and auto_after:
                for w in auto_after:
                    assert w <= max(auto_before) * 0.5 + 0.001


# ═══════════════════════════════════════════════════════════
# Advanced tools tier (BASEMEM_ENABLE_ADVANCED_TOOLS)
# ═══════════════════════════════════════════════════════════

class TestAdvancedToolsTier:
    def _get_tool_names(self):
        """Get current server tool names."""
        from mcp_server.server import server as srv
        return [t.name for t in srv._tool_manager.list_tools()]

    def _reload_server_module(self):
        """Reload the mcp_server.server module via importlib."""
        import importlib
        import sys
        mod = importlib.import_module("mcp_server.server")
        importlib.reload(mod)
        # Update the module reference in sys.modules and clear the old attribute
        sys.modules["mcp_server"].server = mod.server

    def test_optional_tool_noop_when_unset(self, monkeypatch):
        monkeypatch.delenv("BASEMEM_ENABLE_ADVANCED_TOOLS", raising=False)
        self._reload_server_module()
        names = self._get_tool_names()
        assert "compute_similarity" not in names
        assert "rerank" not in names

    def test_optional_tool_registered_when_set(self, monkeypatch):
        monkeypatch.setenv("BASEMEM_ENABLE_ADVANCED_TOOLS", "1")
        self._reload_server_module()
        names = self._get_tool_names()
        assert "compute_similarity" in names
        assert "rerank" in names

    def test_optional_tool_registered_when_true(self, monkeypatch):
        monkeypatch.setenv("BASEMEM_ENABLE_ADVANCED_TOOLS", "true")
        self._reload_server_module()
        names = self._get_tool_names()
        assert "compute_similarity" in names
        assert "rerank" in names

    def test_optional_tool_registered_when_true(self, monkeypatch):
        monkeypatch.setenv("BASEMEM_ENABLE_ADVANCED_TOOLS", "true")
        self._reload_server_module()
        names = self._get_tool_names()
        assert "compute_similarity" in names
        assert "rerank" in names

    def test_functions_always_importable(self):
        from mcp_server.server import compute_similarity, rerank
        assert callable(compute_similarity)
        assert callable(rerank)


# ═══════════════════════════════════════════════════════════
# SessionStart hook
# ═══════════════════════════════════════════════════════════

class TestSessionStartHook:
    HOOK_SCRIPT = str(Path(__file__).parent.parent / "src" / "hooks" / "basemem-session-start.js")

    def test_hook_succeeds_when_mem_not_on_path(self, monkeypatch):
        """Hook must not crash when mem CLI is unavailable."""
        import subprocess
        import os
        import json
        # Remove mem from PATH and mock HOME 
        from pathlib import Path
        Path("/tmp/fakehome/.claude").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("HOME", "/tmp/fakehome")
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        result = subprocess.run(
            ["node", self.HOOK_SCRIPT],
            capture_output=True, text=True, timeout=10,
            env={**__import__('os').environ, "PATH": "/usr/bin:/bin", "HOME": "/tmp/fakehome"},
        )
        assert result.returncode == 0
        # Should emit valid JSON
        lines = result.stdout.strip().splitlines()
        assert len(lines) >= 1
        found_hook = False
        for line in lines:
            data = json.loads(line)
            if "hookSpecificOutput" in data:
                found_hook = True
        assert found_hook

    def test_hook_emits_rules_without_context_when_mem_missing(self, monkeypatch):
        """Without mem, the hook output should still contain BASEMEM_RULES."""
        import subprocess
        from pathlib import Path
        Path("/tmp/fakehome/.claude").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", "/tmp/fakehome")
        result = subprocess.run(
            ["node", self.HOOK_SCRIPT],
            capture_output=True, text=True, timeout=10,
            env={**__import__('os').environ, "PATH": "/usr/bin:/bin", "HOME": "/tmp/fakehome"},
        )
        lines = result.stdout.strip().splitlines()
        
        ctx = None
        for line in lines:
            data = json.loads(line)
            if "hookSpecificOutput" in data:
                ctx = data["hookSpecificOutput"]["additionalContext"]
                break
                
        assert ctx is not None
        assert "MCP tools" in ctx
        assert "getContext" in ctx


def _first_note_id(seeded_db):
    """Helper: get first note id in the seeded planet."""
    _, storage, manager = seeded_db
    notes = manager.search_notes("graph-test-planet")
    return notes[0]["id"] if notes else 1


def _neighbor_weights(seeded_db, note_id):
    """Helper: get neighbor weights for a note (all link types)."""
    _, storage, manager = seeded_db
    return [nb["weight"] for nb in manager.get_note_neighbors(note_id)]


def _auto_neighbor_weights(manager, note_id):
    """Helper: get auto-link neighbor weights only."""
    raw_id = manager._parse_note_id(note_id)
    if raw_id is None:
        return []
    cursor = manager.storage.connection.cursor()
    rows = cursor.execute(
        "SELECT weight FROM note_links WHERE (from_note_id = ? OR to_note_id = ?) AND source = 'auto'",
        (raw_id, raw_id)
    ).fetchall()
    return [r[0] for r in rows]
