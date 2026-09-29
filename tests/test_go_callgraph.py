"""Go call-graph regression.

BaseMem had no Go fixtures, so two real defects went unnoticed until rclone was
indexed:

  * a language with no query file falls back to the generic path, which emits
    symbols and imports but essentially no call edges
  * Go keeps methods in `method_declaration` rather than nesting them under a
    type, so calls inside a method lost their caller entirely

Both made `get_callers` return nothing while the edges looked fine in the DB.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

SOURCE = b"""package fs

type Widget struct{ name string }

func (w *Widget) Refresh() int { return 1 }

func NewWidget() *Widget { return nil }

func helper() int { return 2 }

func (w *Widget) Run() int {
	v := NewWidget()
	if v == nil {
		return helper()
	}
	return v.Refresh() + w.Refresh()
}
"""


@pytest.fixture
def indexed(tmp_path):
    from indexer.indexer import CodeIndexer

    root = tmp_path / "GoProj"
    root.mkdir()
    (root / "widget.go").write_bytes(SOURCE)
    ix = CodeIndexer(str(root))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def test_go_symbols(indexed):
    # search_symbols treats an empty query as browse mode and returns nothing,
    # so look each name up directly.
    for expected in ("Widget", "Refresh", "NewWidget", "helper", "Run"):
        assert indexed.search_symbols(expected, limit=5), f"{expected} was not extracted"


def test_go_produces_call_edges(indexed):
    """The generic fallback emits imports but no calls; Go must not rely on it."""
    total = indexed.conn.execute(
        "SELECT COUNT(*) AS c FROM code_edges WHERE edge_type IN ('calls','member_calls')"
    ).fetchone()["c"]
    assert total > 0, "no call edges at all: go is on the generic path"


def test_method_caller_is_attributed(indexed):
    """A call inside a Go method must name its caller, or get_callers is empty."""
    rows = [
        dict(r) for r in indexed.conn.execute(
            "SELECT from_name, to_name, to_symbol_id FROM code_edges "
            "WHERE project_id = ? AND edge_type = 'member_calls'",
            (indexed.project_id,),
        )
    ]
    assert rows, "no member calls recorded"
    assert all(r["from_name"] for r in rows), (
        f"member calls lost their caller: {[r for r in rows if not r['from_name']]}"
    )


def test_receiver_call_resolves_through_its_declared_type(indexed):
    """`w.Refresh()` must resolve via the receiver's declared type Widget."""
    syms = indexed.search_symbols("Refresh", limit=5)
    assert syms
    callees = indexed.get_callees("Run", "widget.go")
    called = {c["to_name"] for c in callees}
    assert "Refresh" in called, f"Run's callees were {sorted(called)}"
    assert any(c["to_symbol_id"] for c in callees if c["to_name"] == "Refresh"), (
        "w.Refresh() did not resolve to the Widget.Refresh symbol"
    )


def test_get_callers_finds_the_caller(indexed):
    callers = indexed.get_callers("Refresh")
    assert callers, "get_callers(Refresh) returned nothing for a call inside Run"
    assert any(c["symbol_name"] == "Run" for c in callers)


def test_parameter_and_receiver_types_are_recorded(indexed):
    n = indexed.conn.execute(
        "SELECT COUNT(*) AS c FROM code_edges WHERE project_id = ? AND edge_type = 'param_type'",
        (indexed.project_id,),
    ).fetchone()["c"]
    assert n > 0, "receiver/parameter types were not recorded"
