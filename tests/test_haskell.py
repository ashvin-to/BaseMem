"""Haskell: calls are (apply (variable) arg...).

Before these queries haskell produced 3,536 symbols and not a single edge, so
every call graph question about a Haskell repo silently returned nothing.
"""

import pytest

from indexer.parser import CodeParser

SRC = b"""module Main where

import Data.List (sort)

helper :: Int -> Int
helper x = x + 1

main :: IO ()
main = do
  print (helper 4)
  let ys = sort [3, 1]
  print ys
"""


@pytest.fixture
def parsed():
    parser = CodeParser.for_file("Main.hs")
    assert parser is not None, "haskell grammar not available"
    return parser.parse(SRC, "Main.hs")


def test_apply_yields_a_call_edge(parsed):
    _symbols, edges = parsed
    calls = {e["target_name"] for e in edges if e["edge_type"] == "calls"}
    assert "print" in calls
    assert "helper" in calls
    assert "sort" in calls


def test_edges_are_attributed_to_the_enclosing_function(parsed):
    _symbols, edges = parsed
    froms = {e["from_name"] for e in edges if e["edge_type"] == "calls"}
    assert froms == {"main"}, froms


def test_helper_is_still_a_symbol(parsed):
    symbols, _edges = parsed
    assert "helper" in {s["symbol_name"] for s in symbols}


def test_do_block_let_is_not_a_symbol(parsed):
    symbols, _edges = parsed
    assert "ys" not in {s["symbol_name"] for s in symbols}


def test_qualified_call_keeps_its_module_and_is_not_a_free_call():
    parser = CodeParser.for_file("Q.hs")
    src = b"""module Q where
main = print (Data.List.sort [1])
"""
    _symbols, edges = parser.parse(src, "Q.hs")
    free = {e["target_name"] for e in edges if e["edge_type"] == "calls"}
    member = {
        (e["target_receiver"], e["target_name"])
        for e in edges if e["edge_type"] == "member_calls"
    }
    assert ("Data.List.", "sort") in member, member
    assert "Data" not in free, "the qualifier must not become a callee"
    assert "sort" not in free, "a qualified call is not a free function"