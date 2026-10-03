"""Negative queries: WHERE NOT (a)<-[:rel]-()

Nothing in the positive syntax can ask "has no callers" or "calls nothing", which
is why both tools failed the orphan question in the quality benchmark.
"""

import pytest

from indexer.indexer import CodeIndexer
from indexer.query import QueryError, parse
from indexer.query_execute import run


@pytest.fixture
def idx(tmp_path):
    (tmp_path / "a.py").write_text(
        "def used():\n    return 1\n\n\n"
        "def orphan():\n    return 2\n\n\n"
        "def also_used():\n    return used()\n"
    )
    (tmp_path / "b.py").write_text("def caller():\n    return used()\n")
    ix = CodeIndexer(str(tmp_path))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def _names(rows, suffix="a_symbol_name"):
    key = next((k for k in rows[0] if k.endswith("symbol_name")), suffix) if rows else suffix
    return {r[key] for r in rows}


def test_no_inbound_calls(idx):
    rows = run(idx, "MATCH (a:Function) WHERE NOT (a)<-[:calls]-() "
                   "RETURN a.name LIMIT 50")
    got = _names(rows)
    assert "orphan" in got, got
    assert "used" not in got, "used is called by caller"


def test_no_outbound_calls(idx):
    rows = run(idx, "MATCH (a:Function) WHERE NOT (a)-[:calls]->() "
                   "RETURN a.name LIMIT 50")
    got = _names(rows)
    assert "caller" not in got
    assert "orphan" in got


def test_negation_can_be_combined_with_aggregation(idx):
    rows = run(idx, "MATCH (a:Function) WHERE NOT (a)<-[:calls]-() "
                   "RETURN a.name, count(a) AS n LIMIT 50")
    assert rows, "negation plus count should still answer"


def test_negation_needs_a_relationship():
    with pytest.raises(ValueError, match="relationship"):
        run(CodeIndexer("."), "MATCH (a) WHERE NOT (a) RETURN a.name")


def test_negation_needs_a_relationship_in_the_parser():
    with pytest.raises(QueryError, match="relationship"):
        parse("MATCH (a) WHERE NOT (a)<-() RETURN a.name")


def test_unknown_relationship_in_negation_is_rejected():
    with pytest.raises(QueryError, match="unknown relationship"):
        parse("MATCH (a) WHERE NOT (a)<-[:nonsense]-() RETURN a.name")


def test_unknown_label_in_negation_is_rejected():
    with pytest.raises(QueryError, match="unknown label"):
        parse("MATCH (a) WHERE NOT (b:Nonsense)<-[:calls]-() RETURN a.name")


def test_left_arrow_is_one_token():
    plan = parse("MATCH (a) WHERE NOT (a)<-[:calls]-() RETURN a.name")
    assert plan["where"][0]["not"]["direction"] == "in"


def test_anchor_must_be_a_node_in_the_pattern():
    """An anchor that is not in the pattern used to generate silently wrong SQL."""
    with pytest.raises(QueryError, match="not a pattern node"):
        parse("MATCH (a) WHERE NOT (x)<-[:calls]-() RETURN a.name")


def test_anchor_follows_the_pattern_node():
    plan = parse("MATCH (a)-[:calls]->(b) WHERE NOT (b)<-[:imports]-() RETURN a.name")
    assert plan["where"][0]["not"]["anchor"] == "b"


def test_anonymous_far_side_is_accepted():
    for q in (
        "MATCH (a) WHERE NOT (a)<-[:calls]-() RETURN a.name",
        "MATCH (a) WHERE NOT (a)<-[:calls]-(b) RETURN a.name",
        "MATCH (a) WHERE NOT (a)-[:calls]->() RETURN a.name",
    ):
        assert parse(q)["where"], q