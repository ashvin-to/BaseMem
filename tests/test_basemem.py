"""Tests for BaseMem"""

import tempfile
from pathlib import Path

import pytest

from graph.engine import GraphEngine
from models import Edge, EdgeType, Node, NodeType
from storage.db import StorageManager
from storage.sessions import SessionManager


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = StorageManager(str(db_path))
        yield storage
        storage.close()


class TestStorage:
    """Test storage layer"""

    def test_add_node(self, temp_db):
        node = Node(
            title="Test Node",
            content="This is a test",
            node_type=NodeType.CONCEPT,
            keywords=["test", "concept"]
        )
        temp_db.add_node(node)

        retrieved = temp_db.get_node(node.id)
        assert retrieved is not None
        assert retrieved.title == "Test Node"
        assert retrieved.node_type == NodeType.CONCEPT

    def test_add_edge(self, temp_db):
        node1 = Node(title="Node 1", content="Content 1")
        node2 = Node(title="Node 2", content="Content 2")

        temp_db.add_node(node1)
        temp_db.add_node(node2)

        edge = Edge(
            from_id=node1.id,
            to_id=node2.id,
            edge_type=EdgeType.RELATED_TO,
            weight=0.8
        )
        temp_db.add_edge(edge)

        edges = temp_db.get_edges(from_id=node1.id)
        assert len(edges) == 1
        assert edges[0].to_id == node2.id
        assert edges[0].weight == 0.8

    def test_get_neighbors(self, temp_db):
        node1 = Node(title="Node 1", content="Content 1")
        node2 = Node(title="Node 2", content="Content 2")
        node3 = Node(title="Node 3", content="Content 3")

        temp_db.add_node(node1)
        temp_db.add_node(node2)
        temp_db.add_node(node3)

        temp_db.add_edge(Edge(node1.id, node2.id, EdgeType.RELATED_TO))
        temp_db.add_edge(Edge(node1.id, node3.id, EdgeType.CAUSES))

        neighbors = temp_db.get_neighbors(node1.id)
        assert len(neighbors) == 2
        assert node2.id in neighbors
        assert node3.id in neighbors


class TestGraph:
    """Test graph engine"""

    def test_get_neighbors(self, temp_db):
        graph = GraphEngine(temp_db)

        nodes = [Node(title=f"Node {i}", content=f"Content {i}") for i in range(4)]
        for node in nodes:
            temp_db.add_node(node)

        # Create a chain: 0 -> 1 -> 2 -> 3
        for i in range(3):
            edge = Edge(nodes[i].id, nodes[i+1].id, EdgeType.RELATED_TO)
            temp_db.add_edge(edge)

        neighbors = graph.get_neighbors(nodes[0].id, depth=2)
        assert nodes[1].id in neighbors
        assert nodes[2].id in neighbors

    def test_shortest_path(self, temp_db):
        graph = GraphEngine(temp_db)

        nodes = [Node(title=f"Node {i}", content=f"Content {i}") for i in range(4)]
        for node in nodes:
            temp_db.add_node(node)

        # Create a chain
        for i in range(3):
            edge = Edge(nodes[i].id, nodes[i+1].id, EdgeType.RELATED_TO)
            temp_db.add_edge(edge)

        path = graph.get_shortest_path(nodes[0].id, nodes[3].id)
        assert path is not None
        assert len(path) == 4
        assert path[0] == nodes[0].id
        assert path[-1] == nodes[3].id


class TestSessions:
    """Test shared agent memory hierarchy"""

    def test_structured_planet_update_and_read(self, temp_db):
        manager = SessionManager(temp_db)

        planet = manager.update_planet(
            "home-dashboard",
            "BaseMem Integration!",
            status="active",
            goal="Make agent memory clear.",
            current_state="Structured planets are canonical handoff state.",
            next_step="Add CLI commands.",
            file_path="/mnt/Storage/BaseMem/src/basemem/storage/sessions.py",
            command="kb planet read basemem-integration",
        )

        assert planet.id == "planet-basemem-integration"
        assert planet.metadata["topic"] == "basemem-integration"
        assert planet.metadata["status"] == "active"
        assert "## Goal" in planet.content
        assert "Make agent memory clear." in planet.content
        assert "Add CLI commands." in planet.content

        same_planet = manager.get_planet("basemem_integration")
        assert same_planet is not None
        assert same_planet.id == planet.id

    def test_note_links_to_planet_and_updates_summary(self, temp_db):
        manager = SessionManager(temp_db)

        note = manager.add_note(
            "home-dashboard",
            "basemem-integration",
            "decision",
            "Planets store canonical state; moons store transcript archives.",
            agent_id="codex",
        )
        planet = manager.get_planet("basemem-integration")

        assert isinstance(note, dict)
        assert note["id"].startswith("note-")
        assert "Planets store canonical state" in note["content"]
        assert planet is not None
        assert "Planets store canonical state" in planet.content

    def test_moon_archives_are_unique(self, temp_db):
        manager = SessionManager(temp_db)
        manager.log_chat_to_planet("home-dashboard", "basemem-integration", "Started work.", "codex")

        moon_a = manager.ingest_archive_moon("home-dashboard", "basemem-integration", "Transcript A", "codex")
        moon_b = manager.ingest_archive_moon("home-dashboard", "basemem-integration", "Transcript B", "codex")

        assert moon_a.id != moon_b.id
        assert moon_a.metadata["is_private_moon"] is True
        assert moon_b.metadata["is_private_moon"] is True

    def test_build_agent_context_includes_structured_memory(self, temp_db):
        manager = SessionManager(temp_db)
        manager.update_planet(
            "home-dashboard",
            "basemem-integration",
            status="active",
            goal="Keep agent handoff memory small and durable.",
            current_state="Wrapper should read KB first.",
            next_step="Expose a pre-answer context command.",
            handoff="Check the KB before making new decisions.",
        )
        manager.add_note(
            "home-dashboard",
            "basemem-integration",
            "decision",
            "Use kb agent-context as the canonical entrypoint.",
            agent_id="codex",
        )
        manager.log_chat_to_planet(
            "home-dashboard",
            "basemem-integration",
            "Patched the wrapper to export context.",
            "codex",
        )

        context = manager.build_agent_context("basemem integration", query="wrapper")

        assert "# Knowledge Base Context" in context
        assert "Keep agent handoff memory small and durable." in context
        assert "Use kb agent-context as the canonical entrypoint." in context
        assert "Patched the wrapper to export context." in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
