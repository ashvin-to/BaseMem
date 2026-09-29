"""Scope-aware edge resolution.

Two properties matter:
  * a call through an import resolves to the imported file's real symbol id
  * a method call is classified as a member call with a receiver, not flattened
    into a bogus global call named after the method
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "ResProj"
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "thing.js").write_text(
        "export function alpha() { return 1; }\n", encoding="utf-8"
    )
    (root / "app.js").write_text(
        "import { alpha } from './lib/thing';\n"
        "import path from 'path';\n"
        "export function run() {\n"
        "  const v = alpha();\n"
        "  return path.join(v, 'x');\n"
        "}\n",
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


def _edges(ix, edge_type):
    return [dict(r) for r in ix.conn.execute(
        "SELECT file_path, from_name, to_name, to_receiver, to_symbol_id, edge_type "
        "FROM code_edges WHERE project_id = ? AND edge_type = ?",
        (ix.project_id, edge_type),
    )]


def test_imported_symbol_call_resolves_to_real_id(indexed):
    """`alpha()` imported from ./lib/thing must point at thing.js's alpha."""
    calls = _edges(indexed, "calls")
    alpha = [e for e in calls if e["to_name"] == "alpha"]
    assert alpha, "the call to alpha() was not recorded"
    row = indexed.conn.execute(
        "SELECT file_path FROM code_symbols WHERE id = ?", (alpha[0]["to_symbol_id"],)
    ).fetchone()
    assert row, "the call to alpha() did not resolve to a symbol id"
    assert row["file_path"] == "lib/thing.js"


def test_member_call_is_classified_with_receiver(indexed):
    member = [e for e in _edges(indexed, "member_calls") if e["to_name"] == "join"]
    assert member, "path.join() was not recorded as a member call"
    assert member[0]["to_receiver"] == "path"
    # a member call must not also appear as a free call named `join`
    assert not [e for e in _edges(indexed, "calls") if e["to_name"] == "join"]


def test_self_method_call_resolves_to_own_class(tmp_path):
    from indexer.indexer import CodeIndexer

    root = tmp_path / "SelfProj"
    root.mkdir()
    (root / "widget.py").write_text(
        "class Widget:\n"
        "    def render(self):\n"
        "        return self.refresh()\n"
        "\n"
        "    def refresh(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    ix = CodeIndexer(str(root))
    try:
        ix.index_project(_max_workers=1)
        calls = [
            dict(r) for r in ix.conn.execute(
                "SELECT to_name, to_symbol_id FROM code_edges "
                "WHERE project_id = ? AND edge_type = 'member_calls' AND to_name = 'refresh'",
                (ix.project_id,),
            )
        ]
        assert calls, "self.refresh() was not recorded"
        assert calls[0]["to_symbol_id"], "self.refresh() did not resolve to Widget.refresh"
    finally:
        ix.close()


def test_diagnostics_separates_free_and_member_unresolved(indexed):
    d = indexed.get_index_diagnostics()
    assert "unresolved_calls" in d
    assert "unresolved_member_calls" in d
    assert "edges" in d
    assert d["edges"].get("member_calls", 0) > 0
