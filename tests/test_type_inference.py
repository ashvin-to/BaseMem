"""Local type inference for member calls.

`x = Foo()` then `x.method()` has to resolve to Foo's method. Without the
instantiation edge, `x` is a bare local and there is no key to look the method up
on, so the call silently stays unresolved.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "TypeProj"
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "widget.py").write_text(
        "class Widget:\n"
        "    def refresh(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        "from lib.widget import Widget\n"
        "\n"
        "def run():\n"
        "    w = Widget()\n"
        "    w.refresh()\n"
        "    return w\n",
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


def _edge(ix, edge_type, name):
    rows = [
        dict(r) for r in ix.conn.execute(
            "SELECT to_name, to_receiver, from_name, to_symbol_id FROM code_edges "
            "WHERE project_id = ? AND edge_type = ? AND to_name = ?",
            (ix.project_id, edge_type, name),
        )
    ]
    return rows


def test_instantiation_is_recorded(indexed):
    rows = _edge(indexed, "instantiates", "Widget")
    assert rows, "w = Widget() did not produce an instantiates edge"
    assert rows[0]["to_receiver"] == "w", "the variable name must ride on to_receiver"
    assert rows[0]["from_name"] == "run", "the edge must be attributed to the enclosing function"


def test_member_call_resolves_through_inferred_type(indexed):
    rows = _edge(indexed, "member_calls", "refresh")
    assert rows, "w.refresh() was not recorded as a member call"
    assert rows[0]["to_receiver"] == "w", "python must capture the object, not `w.refresh`"
    assert rows[0]["to_symbol_id"], "w.refresh() did not resolve through the inferred type Widget"


def test_instantiation_does_not_resolve_to_itself(indexed):
    """`x = x()` is not a type, and must not be recorded as one."""
    from pathlib import Path

    tmp = Path(indexed.project_root)
    (tmp / "weird.py").write_text("def go():\n    y = y\n    return y\n", encoding="utf-8")
    indexed.index_files(str(tmp), [str(tmp / "weird.py")])
    rows = _edge(indexed, "instantiates", "y")
    assert not rows, "a bare assignment must not be treated as a constructor"
