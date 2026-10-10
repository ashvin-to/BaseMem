"""A C function whose return type is a pointer was invisible to the index.

The `function` query required `function_definition`'s direct `declarator:`
field to be a `function_declarator`. `void *memcpy()` parses as
primitive_type + pointer_declarator > function_declarator > identifier, so the
field held a `pointer_declarator` and the pattern did not match. Across the
kernel that was 41,708 functions, 6% of all C definitions, among them memcpy,
kmalloc and vzalloc: the index held their header declarations and none of the
definitions.

Two of these tests guard how that fix nearly went wrong. A duplicated pattern
makes tree-sitter reject the query, and `_get_query` swallows the error and
returns None, so the language stops extracting with no message anywhere. The
same is true of naming a field the grammar does not have -- `parenthesized_
declarator` has no `declarator:` field.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.languages.c import C_FUNCTION_QUERY, build_function_query  # noqa: E402
from indexer.languages.cpp import CPP_QUERIES  # noqa: E402
from indexer.languages.objc import OBJC_QUERIES  # noqa: E402
from indexer.parser import CodeParser  # noqa: E402


def _parse(source: str, name: str = "probe.c"):
    d = tempfile.mkdtemp()
    f = Path(d) / name
    f.write_text(source)
    parser = CodeParser.for_file(str(f))
    assert parser is not None, "probe file was not recognised"
    return parser.parse(source.encode(), name)


def _names(source: str, name: str = "probe.c"):
    symbols, _ = _parse(source, name)
    return {s["symbol_name"] for s in symbols if s["symbol_type"] == "function"}


# ── the bug ───────────────────────────────────────────────────────────


def test_pointer_returning_function_is_found():
    assert "memcpy" in _names("void *memcpy(void *d, const void *s) { return d; }")


def test_double_pointer_return_is_found():
    assert "alloc" in _names("void **alloc(void) { return 0; }")


def test_triple_pointer_return_is_found():
    assert "deep" in _names("void ***deep(void) { return 0; }")


def test_plain_return_still_found():
    assert "plain" in _names("int plain(void) { return 1; }")


def test_function_returning_pointer_to_function_keeps_a_poor_name():
    """`int (*getfn(void))(int)` names the function `(*getfn(void))`.

    Its outer declarator is a plain function_declarator, so the first pattern
    matches and captures the parenthesized declarator whole. A narrower first
    pattern would fix it, but tree-sitter returns matches in tree order rather
    than pattern order, so the parser's first-match-wins dedup cannot be
    steered that way -- it would mean narrowing `(_)` for every C and C++
    function. 12 functions in the kernel, left alone deliberately.
    """
    assert _names("int (*getfn(void))(int) { return 0; }") == {"(*getfn(void))"}


def test_kr_style_definition_is_found():
    assert "add" in _names("int add(a, b)\nint a;\nint b;\n{ return a + b; }")


# ── the query itself ──────────────────────────────────────────────────


@pytest.mark.parametrize("query", [C_FUNCTION_QUERY, CPP_QUERIES["function"]])
def test_query_compiles(query):
    """A rejected query silently disables the whole language."""
    from tree_sitter import Query

    d = tempfile.mkdtemp()
    f = Path(d) / "probe.c"
    f.write_text("int f(void) { return 1; }\n")
    parser = CodeParser.for_file(str(f))
    Query(parser.grammar, query)


def test_no_duplicate_patterns():
    """tree-sitter rejects an impossible pattern, and a repeat counts as one."""
    lines = [ln for ln in C_FUNCTION_QUERY.splitlines() if ln.strip()]
    assert len(lines) == len(set(lines))
    assert len(lines) == 10


def test_every_pattern_names_only_real_grammar_fields():
    """`parenthesized_declarator` has no `declarator:` field."""
    assert "parenthesized_declarator declarator:" not in C_FUNCTION_QUERY
    assert "parenthesized_declarator (identifier) @name" in C_FUNCTION_QUERY


def test_objc_keeps_its_identifier_capture():
    assert "(identifier) @name" in OBJC_QUERIES["function"]
    assert "(_) @name" not in OBJC_QUERIES["function"]


def test_objc_and_cpp_share_the_builder():
    assert OBJC_QUERIES["function"] == build_function_query("(identifier) @name")
    assert CPP_QUERIES["function"] == build_function_query()


def test_a_plain_query_would_have_missed_the_pointer_case():
    """Pins why the extra patterns exist at all."""
    from tree_sitter import Query, QueryCursor

    d = tempfile.mkdtemp()
    f = Path(d) / "probe.c"
    source = b"void *memcpy(void *d, const void *s) { return d; }\n"
    f.write_bytes(source)
    parser = CodeParser.for_file(str(f))
    root = parser.parser.parse(source).root_node
    old = "(function_definition declarator: (function_declarator declarator: (_) @name)) @symbol"
    assert QueryCursor(Query(parser.grammar, old)).matches(root) == []
    assert len(QueryCursor(Query(parser.grammar, C_FUNCTION_QUERY)).matches(root)) == 1
