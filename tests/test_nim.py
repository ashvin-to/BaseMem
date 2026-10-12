"""Nim queries: the grammar has no `methodCall` node."""

import pytest

from indexer.parser import CodeParser

NIM = b"""
type
  Widget = ref object of RootObj
    name: string

proc build(target: string): string =
  let parts = target.splitFile(".")
  result = parts[0]
  for line in result.splitLines():
    echo line.strip()
  var w = Widget(name: "x")
  echo w.name
"""


@pytest.fixture
def parsed():
    parser = CodeParser.for_file("sample.nim")
    assert parser is not None, "nim grammar not available"
    return parser.parse(NIM, "sample.nim")


def test_dotted_calls_become_member_calls(parsed):
    symbols, edges = parsed
    members = [e for e in edges if e["edge_type"] == "member_calls"]
    pairs = {(e["target_receiver"], e["target_name"]) for e in members}
    assert ("target", "splitFile") in pairs
    assert ("result", "splitLines") in pairs
    assert ("line", "strip") in pairs
    assert ("w", "name") in pairs


def test_receiver_is_the_bare_name_not_the_whole_expression(parsed):
    _symbols, edges = parsed
    for e in edges:
        if e["edge_type"] == "member_calls":
            assert e["target_receiver"] and "." not in e["target_receiver"]


def test_dotted_call_is_not_also_a_free_call(parsed):
    """`result.splitLines()` must not record a free call to `result`."""
    _symbols, edges = parsed
    free = {e["target_name"] for e in edges if e["edge_type"] == "calls"}
    assert "result" not in free
    assert "target" not in free
    assert "line" not in free
    assert "w" not in free


def test_command_style_call_recorded(parsed):
    """`echo x` is a cmdCall, not a functionCall."""
    _symbols, edges = parsed
    free = {e["target_name"] for e in edges if e["edge_type"] == "calls"}
    assert "echo" in free
