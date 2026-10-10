r"""`!~` — the negated regex match, so a negative question can also exclude
something by pattern. Without it "find unused code" is unanswerable in one
query: the orphans are buried under hundreds of test functions.

`=~` was substring search on the longest literal run, so the pattern
`_test\.go$` also matched `contest.go`. It is a real regex match now, via a
`regexp` function on the connection."""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.indexer import _regexp  # noqa: E402
from indexer.query import QueryError, _TOKEN, parse  # noqa: E402
from indexer.query_execute import _where  # noqa: E402


def test_bang_tilde_is_a_token():
    assert _TOKEN.match("!~") is not None


def test_parses_to_the_bang_tilde_operator():
    plan = parse("MATCH (a) WHERE a.file !~ '_test\\.go$' RETURN a.name")
    clause = plan["where"][0]
    assert clause["op"] == "!~"
    assert clause["value"] == "_test\\.go$"


def test_executes_as_not_regexp():
    sql, params = _where({"ident": "a", "prop": "file", "op": "!~", "value": "_test"}, "a")
    assert sql == "a.file_path NOT REGEXP ?"
    assert params == ["_test"]


def test_regex_match_executes_as_regexp():
    sql, _ = _where({"ident": "a", "prop": "name", "op": "=~", "value": "Handler"}, "a")
    assert sql == "a.symbol_name REGEXP ?"


def test_combines_with_a_negated_pattern():
    plan = parse(
        r"MATCH (a:Function) WHERE NOT (a)<-[:calls]-() "
        r"AND a.file !~ '_test\.go$' RETURN a.name"
    )
    assert plan["where_joiner"] == "AND"
    assert plan["where"][0]["not"] is not None
    assert plan["where"][1]["op"] == "!~"


def test_bang_tilde_needs_a_quoted_pattern():
    with pytest.raises(QueryError):
        parse("MATCH (a) WHERE a.file !~ _test RETURN a.name")


def test_regexp_callback_searches_rather_than_prefix_matches():
    assert _regexp("_test", "a_test_helper.go") == 1
    assert _regexp(r"_test\.go$", "command_test.go") == 1
    # The bug this replaces: the literal run '_test' matched either of these.
    assert _regexp(r"_test\.go$", "contest.go") == 0
    assert _regexp(r"_test\.go$", "latest.go") == 0


def test_regexp_callback_survives_a_bad_pattern():
    assert _regexp("[unclosed", "anything") == 0


def test_regexp_callback_treats_null_as_no_match():
    assert _regexp("x", None) == 0


def test_regexp_is_usable_from_sql():
    conn = sqlite3.connect(":memory:")
    conn.create_function("regexp", 2, _regexp)
    got = conn.execute(
        r"SELECT v FROM (SELECT 'contest.go' AS v UNION SELECT 'command_test.go') "
        r"WHERE v REGEXP ?",
        (r"_test\.go$",),
    ).fetchall()
    assert got == [("command_test.go",)]
    got = conn.execute(
        r"SELECT v FROM (SELECT 'contest.go' AS v UNION SELECT 'command_test.go') "
        r"WHERE v NOT REGEXP ?",
        (r"_test\.go$",),
    ).fetchall()
    assert got == [("contest.go",)]


def test_documented_handler_example_still_matches():
    assert re.search(".*Handler.*", "EventHandler") is not None
