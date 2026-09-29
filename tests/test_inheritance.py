"""Inheritance edges and chain-aware method resolution.

A call through a subclass instance must resolve to a method declared on a base
class, otherwise the call graph breaks at every inheritance boundary.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "InheritProj"
    root.mkdir()
    (root / "shapes.py").write_text(
        "class Base:\n"
        "    def refresh(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Middle(Base):\n"
        "    def extra(self):\n"
        "        return 2\n"
        "\n"
        "\n"
        "class Leaf(Middle):\n"
        "    pass\n"
        "\n"
        "\n"
        "def run():\n"
        "    leaf = Leaf()\n"
        "    return leaf.refresh()\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def indexed(proj):
    from indexer.indexer import CodeIndexer

    ix = CodeIndexer(str(proj))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def test_inherits_edges_are_recorded(indexed):
    rows = [
        dict(r) for r in indexed.conn.execute(
            "SELECT from_name, to_name FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'inherits'",
            (indexed.project_id,),
        )
    ]
    pairs = {(r["from_name"], r["to_name"]) for r in rows}
    assert ("Middle", "Base") in pairs
    assert ("Leaf", "Middle") in pairs


def test_method_resolves_two_levels_up_the_chain(indexed):
    rows = [
        dict(r) for r in indexed.conn.execute(
            "SELECT to_name, to_receiver, to_symbol_id FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'member_calls' AND to_name = 'refresh'",
            (indexed.project_id,),
        )
    ]
    assert rows, "leaf.refresh() was not recorded"
    assert rows[0]["to_symbol_id"], "leaf.refresh() did not resolve to Base.refresh"
    target = indexed.conn.execute(
        "SELECT file_path, start_line FROM code_symbols WHERE id = ?", (rows[0]["to_symbol_id"],)
    ).fetchone()
    assert target["file_path"] == "shapes.py"


def test_self_inheritance_is_not_recorded(tmp_path):
    from indexer.indexer import CodeIndexer

    root = tmp_path / "SelfProj"
    root.mkdir()
    (root / "loop.py").write_text("class Loop(Loop):\n    pass\n", encoding="utf-8")
    ix = CodeIndexer(str(root))
    try:
        ix.index_project(_max_workers=1)
        n = ix.conn.execute(
            "SELECT COUNT(*) AS c FROM code_edges WHERE project_id = ? AND edge_type = 'inherits'",
            (ix.project_id,),
        ).fetchone()["c"]
        assert n == 0, "class Loop(Loop) is not inheritance and must be ignored"
    finally:
        ix.close()
