"""Tests for BaseMem"""

import pytest
import tempfile
from pathlib import Path
import asyncio

from src.basemem.models import Node, NodeType, Edge, EdgeType
from src.basemem.storage.db import StorageManager
from src.basemem.retrieval.engine import RetrievalEngine
from src.basemem.graph.engine import GraphEngine
from src.basemem.processing.pipeline import ProcessingPipeline


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


class TestProcessing:
    """Test processing pipeline"""

    def test_ingest_text(self, temp_db):
        pipeline = ProcessingPipeline(temp_db)
        text = "This is a test sentence. This is another test sentence."

        nodes = asyncio.run(pipeline.ingest_text(text, source="test"))

        assert len(nodes) > 0
        assert all(isinstance(n, Node) for n in nodes)
        assert all(n.content for n in nodes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
