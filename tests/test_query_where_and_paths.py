"""OR/AND in WHERE, IN lists, anonymous nodes and multi-hop.

Each of these is a question class the quality benchmark showed was unanswerable:
two-hop traversal, disjunction, and membership over a name set.
"""

import pytest

from indexer.indexer import CodeIndexer
from indexer.query import QueryError, parse
from indexer.query_execute import run


@pytest.fixture
def idx(tmp_path):
    (tmp_path / "a.py").write_text(
        "def leaf():\n    return 1\n\n\n"
        "def used():\n    return leaf()\n\n\n"
        "def middle():\n    return used()\n"
    )
    (tmp_path / "b.py").write_text(
        "def other():\n    return 1\n\n\n"
        "def caller():\n    return other()\n\n\n"
        "def cross():\n    return used()\n"
    )
    ix = CodeIndexer(str(tmp_path))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def _names(rows, suffix="symbol_name"):
    if not rows:
        return set()
    key = next(k for k in rows[0] if k.endswith(suffix))
    return {r[key] for r in rows}


# ── OR / AND ────────────────────────────────────────────────────────


def test_or_returns_both_sides(idx):
    rows = run(idx, "MATCH (a:Function) WHERE a.file = 'a.py' OR a.file = 'b.py' "
                   "RETURN a.name")
    assert {"used", "other"} <= _names(rows)


def test_or_is_not_and(idx):
    rows = run(idx, "MATCH (a:Function) WHERE a.file = 'a.py' OR a.file = 'b.py' "
                   "RETURN a.name")
    assert "used" in _names(rows) and "other" in _names(rows)


def test_and_narrows(idx):
    both = _names(run(idx, "MATCH (a:Function) WHERE a.file = 'a.py' AND a.name = 'used' "
                          "RETURN a.name"))
    assert both == {"used"}


def test_or_across_both_nodes(idx):
    """A clause names its own node; both must not be applied to a."""
    rows = run(idx, "MATCH (a)-[:calls]->(b) WHERE a.file = 'b.py' AND b.file = 'a.py' "
                   "RETURN a.name")
    assert _names(rows) == {"cross"}


def test_mixing_and_with_or_is_rejected():
    with pytest.raises(QueryError, match="parentheses"):
        parse("MATCH (a) WHERE a.name = 'x' AND a.file = 'y' OR a.name = 'z'")


# ── IN ───────────────────────────────────────────────────────────────


def test_in_matches_any_member(idx):
    rows = run(idx, "MATCH (a:Function) WHERE a.name IN ['used', 'other'] "
                   "RETURN a.name")
    assert _names(rows) == {"used", "other"}


def test_in_excludes_non_members(idx):
    rows = run(idx, "MATCH (a:Function) WHERE a.name IN ['used'] RETURN a.name")
    assert "other" not in _names(rows)


def test_in_needs_a_list():
    with pytest.raises(QueryError, match="list"):
        parse("MATCH (a) WHERE a.name IN 'x' RETURN a.name")


def test_in_list_must_close():
    with pytest.raises(QueryError, match="closing bracket"):
        parse("MATCH (a) WHERE a.name IN ['x', 'y' RETURN a.name")


def test_empty_in_is_rejected():
    with pytest.raises(QueryError, match="at least one"):
        parse("MATCH (a) WHERE a.name IN [] RETURN a.name")


# ── anonymous nodes and multi-hop ────────────────────────────────────


def test_anonymous_node_parses():
    plan = parse("MATCH (a)-[:calls]->() RETURN a.name")
    assert len(plan["pattern"]["hops"]) == 1
    assert plan["pattern"]["b"]["anon"] is True


def test_two_hop_chain_parses():
    plan = parse("MATCH (a)-[:calls]->()->[:calls]->() RETURN a.name")
    assert len(plan["pattern"]["hops"]) == 2


def test_two_hop_finds_a_real_path(idx):
    rows = run(idx, "MATCH (a)-[:calls]->(m)-[:calls]->(b) RETURN a.name, m.name")
    got = {(r["a_symbol_name"], r["m_symbol_name"]) for r in rows}
    assert ("middle", "used") in got, got
    assert ("middle", "leaf") not in got, got


def test_two_hop_with_a_filter_on_the_start(idx):
    rows = run(idx, "MATCH (a)-[:calls]->(m)-[:calls]->(b) WHERE a.name = 'middle' "
                   "RETURN a.name, m.name")
    assert [r["m_symbol_name"] for r in rows] == ["used"]


def test_filter_on_an_intermediate_node(idx):
    rows = run(idx, "MATCH (a)-[:calls]->(m)-[:calls]->(b) WHERE m.name = 'used' "
                   "RETURN a.name, b.name")
    assert sorted(r["a_symbol_name"] for r in rows) == ["cross", "middle"]


def test_returning_an_unknown_node_is_rejected(idx):
    with pytest.raises(ValueError, match="not a node"):
        run(idx, "MATCH (a)-[:calls]->(m)-[:calls]->(b) RETURN zzz.name")


def test_relation_without_an_arrow_is_rejected():
    with pytest.raises(QueryError, match="arrow"):
        parse("MATCH (a)-[:calls] RETURN a.name")