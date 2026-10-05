"""Top-level-only symbol queries.

A query cannot express "has no ancestor of type X", so OCaml's `let` nesting
meant every local binding was recorded as a symbol: `value_definition` appears
inside another `value_definition` for each `let ... in`, and matching all of them
put 8,620 symbols in a single `types.ml` -- locals, `_`, and C enum constants
swept in from a header.

A query name ending in `_toplevel` now means "skip a match whose declared node
is nested inside another node of the same type". It is opt-in because a blanket
rule would drop Java inner classes and Python nested functions, which are real.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

OCAML = b"""let top = 1

let f x =
  let local1 = x + 1 in
  let local2 = local1 * 2 in
  local2

type t = A | B
"""

HASKELL = b"""topLevel = 1

g x = do
  let inner = x + 1
  return inner
"""


def _names(filename, src, tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    symbols, _edges = parser.parse(src, filename)
    return {s["symbol_name"] for s in symbols}


def test_ocaml_locals_are_not_symbols(tmp_path):
    got = _names("a.ml", OCAML, tmp_path)
    assert "top" in got and "f" in got, f"top-level bindings missing: {sorted(got)}"
    assert "local1" not in got, f"a local let leaked into the symbol table: {sorted(got)}"
    assert "local2" not in got, f"a local let leaked into the symbol table: {sorted(got)}"


def test_haskell_do_block_lets_are_filtered(tmp_path):
    """A do-block `let` was leaking as a symbol and still is pinned here.

    It is a `bind` not nested inside another `bind`, so the shadowing rule did
    not catch it -- measured on shellcheck this moved the count only 3,829 ->
    3,534, against OCaml's 18,262 -> 6,383. It was also mis-attributing the
    calls inside it to the local binding instead of the enclosing function,
    because `bind` is haskell's only declaration node.
    """
    got = _names("a.hs", HASKELL, tmp_path)
    assert "topLevel" in got, f"top-level binding missing: {sorted(got)}"
    assert "inner" not in got, (
        "haskell do-block lets are filtered again; if this is deliberate, "
        f"update the notes. got {sorted(got)}"
    )


def test_toplevel_is_opt_in(tmp_path):
    """Java inner classes and Python nested defs are real symbols."""
    from indexer.parser import CodeParser

    java = b"class Outer { class Inner { } }"
    (tmp_path / "A.java").write_bytes(java)
    got = _names("A.java", java, tmp_path)
    assert {"Outer", "Inner"} <= got, f"nested class dropped: {sorted(got)}"

    py = b"def outer():\n    def inner():\n        return 1\n    return inner\n"
    (tmp_path / "m.py").write_bytes(py)
    got = _names("m.py", py, tmp_path)
    assert {"outer", "inner"} <= got, f"nested def dropped: {sorted(got)}"


def test_shadow_detection_helper(tmp_path):
    from indexer.parser import CodeParser, _is_shadowed

    f = tmp_path / "a.ml"
    f.write_bytes(OCAML)
    root = CodeParser.for_file("a.ml").parser.parse(OCAML).root_node

    seen = []

    def walk(node):
        if node.type == "value_definition":
            seen.append(_is_shadowed(node))
        for child in node.named_children:
            walk(child)

    walk(root)
    assert seen, "no value_definition found"
    assert seen[0] is False, "the top-level `let top` is not shadowed"
    assert any(seen), "the local lets inside `f` should be reported as shadowed"
