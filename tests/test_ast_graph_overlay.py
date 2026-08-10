"""Tests for AST Call-Graph Indexing integration into BaseMem graph nodes (Task-42)."""

import os
import tempfile
from pathlib import Path
import pytest

from storage.db import StorageManager
from models import Node, NodeType
from graph.engine import GraphEngine
from indexer.indexer import CodeIndexer


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "TestASTProject"
        p.mkdir()

        # Create Python source files with definitions and calls
        (p / "math_utils.py").write_text(
            "def add_numbers(a, b):\n"
            "    return a + b\n\n"
            "def multiply_numbers(a, b):\n"
            "    return a * b\n"
        )
        (p / "calculator.py").write_text(
            "import math_utils\n\n"
            "class Calculator:\n"
            "    def calculate(self, x, y):\n"
            "        sum_val = math_utils.add_numbers(x, y)\n"
            "        prod_val = math_utils.multiply_numbers(x, y)\n"
            "        return sum_val, prod_val\n"
        )

        # Index project AST
        indexer = CodeIndexer(str(p))
        indexer.index_project()
        indexer.close()

        yield p


def test_code_indexer_get_virtual_graph_nodes(temp_project):
    indexer = CodeIndexer(str(temp_project))
    vgraph = indexer.get_virtual_graph_nodes(limit=50)
    indexer.close()

    assert "nodes" in vgraph
    assert "edges" in vgraph
    assert len(vgraph["nodes"]) >= 3

    # Verify nodes contain add_numbers and Calculator
    titles = [n["title"] for n in vgraph["nodes"].values()]
    assert "add_numbers" in titles
    assert "Calculator" in titles or "calculate" in titles

    # Verify calls edges exist
    edge_types = [e["edge_type"] for e in vgraph["edges"]]
    assert "calls" in edge_types or "imports" in edge_types


def test_graph_engine_virtual_code_overlay(temp_project):
    db_path = str(temp_project / ".basemem.db")
    storage = StorageManager(db_path)

    # Add a memory note referencing add_numbers
    mem_node = Node(
        id="note-101",
        title="Implementation of Calculator with add_numbers",
        content="Calculations depend on add_numbers helper from math_utils.",
        node_type=NodeType.CONCEPT,
    )
    storage.add_node(mem_node)

    engine = GraphEngine(storage)
    overlay = engine.get_virtual_code_overlay(project_root=str(temp_project))

    assert "nodes" in overlay
    assert "edges" in overlay
    assert len(overlay["nodes"]) > 0

    # Verify auto-bridge edge REFERENCES_CODE connects memory note to code symbol
    bridge_edges = [e for e in overlay["edges"] if e.get("edge_type") == "REFERENCES_CODE"]
    assert len(bridge_edges) >= 1
    assert bridge_edges[0]["from_id"] == "note-101"


def test_graph_engine_get_neighbors_include_code(temp_project):
    db_path = str(temp_project / ".basemem.db")
    storage = StorageManager(db_path)

    mem_node = Node(
        id="note-102",
        title="add_numbers math refactor",
        content="Refactoring add_numbers in math_utils.",
        node_type=NodeType.TASK,
    )
    storage.add_node(mem_node)

    engine = GraphEngine(storage)
    neighbors = engine.get_neighbors("note-102", depth=1, include_code=True, project_root=str(temp_project))

    # Should return virtual AST code nodes alongside memory nodes
    assert len(neighbors) > 0
    node_ids = list(neighbors.keys())
    assert any(nid.startswith("code:") for nid in node_ids)
