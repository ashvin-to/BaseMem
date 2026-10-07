"""Relation alternation: `[:calls|member_calls]`.

A single relation per hop makes multi-hop nearly useless in practice. Measured
on cobra: `calls`->`calls` two hops yields 0 paths, while `calls|member_calls` on
both hops yields 922, because real Go call chains alternate between a bare call
and a method call.

The `|` token is asserted before anything is built on it. An earlier attempt at
this hung the parser because the token was silently dropped by the regex and the
pattern looped forever waiting for it.
"""

import pytest

from indexer.query import EDGES, QueryError, parse
from indexer.query import _TOKEN


def _tokens(q: str) -> list[str]:
    return [m.group(0) for m in _TOKEN.finditer(q) if m.group(0).strip()]


def test_pipe_is_a_token():
    """Guard first: everything below assumes this."""
    assert "|" in _tokens("[:calls|member_calls]"), "pipe is not tokenized"


def test_single_relation_still_parses():
    plan = parse("MATCH (a)-[:calls]->(b) RETURN a.name")
    assert plan["pattern"]["hops"][0]["rel"] == "calls"


def test_alternation_is_recorded_per_hop():
    plan = parse("MATCH (a)-[:calls|member_calls]->(b) RETURN a.name")
    assert plan["pattern"]["hops"][0]["rels"] == ["calls", "member_calls"]


def test_single_relation_yields_a_one_item_list():
    plan = parse("MATCH (a)-[:calls]->(b) RETURN a.name")
    assert plan["pattern"]["hops"][0]["rels"] == ["calls"]


def test_alternation_at_each_hop_is_independent():
    plan = parse("MATCH (a)-[:calls|member_calls]->(m)-[:imports]->(b) RETURN a.name")
    rels = [h["rels"] for h in plan["pattern"]["hops"]]
    assert rels == [["calls", "member_calls"], ["imports"]]


def test_three_way_alternation():
    plan = parse("MATCH (a)-[:calls|member_calls|inherits]->(b) RETURN a.name")
    assert plan["pattern"]["hops"][0]["rels"] == ["calls", "member_calls", "inherits"]


def test_order_does_not_matter():
    plan = parse("MATCH (a)-[:member_calls|calls]->(b) RETURN a.name")
    assert set(plan["pattern"]["hops"][0]["rels"]) == {"calls", "member_calls"}


def test_unknown_member_is_rejected():
    with pytest.raises(QueryError, match="unknown relationship"):
        parse("MATCH (a)-[:calls|nonsense]->(b) RETURN a.name")


def test_every_alternation_member_must_be_known():
    for r in EDGES:
        plan = parse(f"MATCH (a)-[:{r}|calls]->(b) RETURN a.name")
        assert plan["pattern"]["hops"][0]["rels"] == [r, "calls"]


def test_alternation_needs_a_relation_first():
    with pytest.raises(QueryError):
        parse("MATCH (a)-[|calls]->(b) RETURN a.name")


def test_trailing_pipe_is_rejected():
    with pytest.raises(QueryError):
        parse("MATCH (a)-[:calls|]->(b) RETURN a.name")