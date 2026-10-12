"""The code_query subset.

Two things must hold: the supported forms parse and execute, and everything
outside the subset is rejected. Rejection is the security property — the executor
builds its own parameterised SQL, so a query that reaches the SQL string verbatim
would be a way to run arbitrary statements.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

from indexer.query import QueryError, describe, parse  # noqa: E402

VALID = [
    "MATCH (a:Function) RETURN a.name LIMIT 3",
    "MATCH (a) WHERE a.name = 'staleness' RETURN a.name",
    "MATCH (a) WHERE a.file ~ 'indexer/' RETURN a.name, a.file LIMIT 5",
    "MATCH (a)-[:CALLS]->(b) WHERE a.name =~ '.*Handler.*' RETURN a.name, b.name",
    "MATCH (a)--[:INHERITS]->(b) RETURN a.name, b.name LIMIT 4",
    "MATCH (a:Class)-[:INHERITS]->(b) RETURN a.name LIMIT 3",
    "MATCH (a)-[:MEMBER_CALLS]->(b) RETURN a.name, b.name",
]

REJECTED = [
    "",                                   # empty
    "DELETE FROM code_symbols",           # not a MATCH
    "DROP TABLE code_symbols",
    "MATCH (a) RETURN a; DROP TABLE t",   # trailing statement
    "MATCH (a:Bogus) RETURN a",           # unknown label
    "MATCH (a)-[:NOPE]->(b) RETURN a",    # unknown relationship
    "MATCH (a) RETURN",                   # no fields
    "MATCH (a RETURN a",                  # unbalanced
    "UPDATE code_symbols SET x = 1",
]


@pytest.mark.parametrize("q", VALID, ids=range(len(VALID)))
def test_valid_queries_parse(q):
    plan = parse(q)
    assert plan["returns"]
    assert plan["limit"] >= 1


@pytest.mark.parametrize("q", REJECTED, ids=range(len(REJECTED)))
def test_invalid_queries_are_rejected(q):
    with pytest.raises(QueryError):
        parse(q)


def test_both_dash_spellings_work():
    single = parse("MATCH (a)-[:CALLS]->(b) RETURN a.name, b.name")
    double = parse("MATCH (a)--[:CALLS]->(b) RETURN a.name, b.name")
    assert single["pattern"]["rel"] == double["pattern"]["rel"] == "calls"


def test_both_bracket_spellings_work():
    with_colon = parse("MATCH (a)-[:CALLS]->(b) RETURN a.name")
    without = parse("MATCH (a)-[CALLS]->(b) RETURN a.name")
    assert with_colon["pattern"]["rel"] == without["pattern"]["rel"] == "calls"


def test_limit_is_bounded():
    assert parse("MATCH (a) RETURN a.name LIMIT 99999")["limit"] == 1000
    assert parse("MATCH (a) RETURN a.name LIMIT 0")["limit"] == 1


def test_describe_lists_the_subset():
    text = describe()
    for expected in ("MATCH", "LIMIT", "calls", "inherits", "function"):
        assert expected in text


@pytest.fixture
def indexed(tmp_path):
    from indexer.indexer import CodeIndexer

    root = tmp_path / "QProj"
    root.mkdir()
    (root / "app.py").write_text(
        "class Base:\n"
        "    def refresh(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Child(Base):\n"
        "    def run(self):\n"
        "        return self.refresh()\n",
        encoding="utf-8",
    )
    ix = CodeIndexer(str(root))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


def test_label_filter(indexed):
    from indexer.query_execute import run

    rows = run(indexed, "MATCH (a:Class) RETURN a.name")
    assert {r["symbol_name"] for r in rows} == {"Base", "Child"}


def test_inheritance_traversal(indexed):
    from indexer.query_execute import run

    rows = run(indexed, "MATCH (a)-[:INHERITS]->(b) RETURN a.name, b.name")
    assert [(r["a_symbol_name"], r["b_symbol_name"]) for r in rows] == [("Child", "Base")]


def test_return_fields_come_from_the_right_node(indexed):
    """A regression guard: projecting both sides from one table made every row
    look like a self-reference."""
    from indexer.query_execute import run

    rows = run(indexed, "MATCH (a)-[:INHERITS]->(b) RETURN a.name, b.name")
    assert rows
    for r in rows:
        assert r["a_symbol_name"] != r["b_symbol_name"]


def test_where_filters(indexed):
    from indexer.query_execute import run

    rows = run(indexed, "MATCH (a) WHERE a.name = 'Child' RETURN a.name")
    assert [r["symbol_name"] for r in rows] == ["Child"]


def test_unknown_field_is_reported(indexed):
    from indexer.query_execute import run

    with pytest.raises(ValueError):
        run(indexed, "MATCH (a) WHERE a.nonsense = 'x' RETURN a.name")
