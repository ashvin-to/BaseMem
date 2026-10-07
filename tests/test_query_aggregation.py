"""Aggregation in code_query: count(), AS, ORDER BY.

`MATCH (a)-[:REL]->(b) RETURN a.name, count(b) AS callers ORDER BY callers DESC`
is the one question class BaseMem could not answer at all before this, which the
query-quality benchmark showed as its only loss to cbm.
"""

import pytest

from indexer.indexer import CodeIndexer
from indexer.query import QueryError, describe, parse
from indexer.query_execute import run


@pytest.fixture
def idx(tmp_path):
    (tmp_path / "a.py").write_text(
        "def hot():\n    return 1\n\n\n"
        "def cold():\n    return 2\n"
    )
    (tmp_path / "b.py").write_text(
        "def one():\n    return hot()\n\n\n"
        "def two():\n    return hot()\n\n\n"
        "def three():\n    return cold()\n"
    )
    ix = CodeIndexer(str(tmp_path))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def _by_name(rows):
    if not rows:
        return {}
    name = next(k for k in rows[0] if k.endswith("symbol_name"))
    return {r[name]: r for r in rows}


# ── parsing ────────────────────────────────────────────────────────


def test_count_requires_an_alias():
    with pytest.raises(QueryError, match="alias"):
        parse("MATCH (a)-[:calls]->(b) RETURN a.name, count(b)")


def test_count_of_unknown_node_is_rejected(idx):
    with pytest.raises(ValueError, match="count"):
        run(idx, "MATCH (a) RETURN count(z) AS n")


def test_documented_examples_all_parse():
    """Every form in describe() must parse, or the docs lie."""
    import re

    seen = 0
    for line in describe().splitlines():
        m = re.match(r"^\s{2}(MATCH .*)$", line)
        # `|` marks alternatives and `...` is a placeholder, not literal syntax.
        if not m or "|" in m.group(1) or "..." in m.group(1):
            continue
        example = m.group(1).replace("REL", "calls").replace("Label", "Function")
        example = re.sub(r"\bn\b", "5", example)
        example = example.replace("LIMIT 5", "LIMIT 5")
        parse(example)  # must not raise
        seen += 1
    assert seen >= 3, f"only {seen} parsed; describe() changed shape"


# ── execution ──────────────────────────────────────────────────────


def test_count_ranks_by_frequency(idx):
    rows = run(idx, "MATCH (a)-[:calls]->(b) RETURN b.name, count(a) AS callers "
                   "ORDER BY callers DESC")
    got = _by_name(rows)
    assert got["hot"]["callers"] == 2
    assert got["cold"]["callers"] == 1
    assert list(got)[0] == "hot", "highest first"


def test_order_by_ascending_reverses(idx):
    desc = _by_name(run(idx, "MATCH (a)-[:calls]->(b) RETURN b.name, "
                            "count(a) AS c ORDER BY c DESC"))
    asc = _by_name(run(idx, "MATCH (a)-[:calls]->(b) RETURN b.name, "
                           "count(a) AS c ORDER BY c ASC"))
    assert list(desc)[0] == list(asc)[-1]


def test_count_star_on_one_node(idx):
    rows = run(idx, "MATCH (a:Function) RETURN count(*) AS total")
    assert len(rows) == 1
    assert rows[0]["total"] >= 4


def test_alias_on_a_plain_field(idx):
    rows = run(idx, "MATCH (a) RETURN a.name AS symbol LIMIT 3")
    assert rows and "symbol" in rows[0]


def test_limit_still_applies_to_aggregates(idx):
    rows = run(idx, "MATCH (a)-[:calls]->(b) RETURN b.name, count(a) AS c "
                   "ORDER BY c DESC LIMIT 1")
    assert len(rows) == 1


def test_queries_without_aggregates_are_unchanged(idx):
    rows = run(idx, "MATCH (a) RETURN a.name, a.file LIMIT 3")
    assert len(rows) == 3
    assert all("a_symbol_name" in r for r in rows)


def test_order_by_unknown_column_is_rejected(idx):
    """ORDER BY only accepts a returned alias or a known field, never raw SQL."""
    with pytest.raises(ValueError, match="cannot order by"):
        run(idx, "MATCH (a) RETURN a.name AS n ORDER BY nonsense")


def test_accept_word_is_case_insensitive():
    """It uppercased the token but compared against the argument as-is."""
    plan = parse("match (a) return a.name limit 2")
    assert plan["limit"] == 2