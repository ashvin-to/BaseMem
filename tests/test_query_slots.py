"""Every query-file key must be a slot the parser actually runs.

This has now bitten four times, always silently. A query filed under a name the
parser never looks up compiles fine, matches nothing, and reports as "this
language produces no macros" rather than as an error:

  * lua's `function_signature` and `field_call` -- a 20KB file went from 31
    symbols to 0
  * C's `macro`, which had been in the query file since it was written
  * C's `struct_typedef`, `struct_toplevel`, `enum_toplevel`, `enumerator`

The cost is always the same: coverage silently disappears and the only symptom
is a disappointing number much later. So the check is a test.
"""

import re
import pytest

pytest.importorskip("tree_sitter_language_pack")

# Slots the symbol extractor iterates. Order matters -- the first match for a
# given byte range wins -- but membership is what this test guards.
SYMBOL_SLOTS = {
    "function", "class", "resource", "method", "assigned_method",
    "assigned_method_literal", "method_signature", "interface", "type_alias",
    "enum", "struct", "trait", "impl", "constructor", "namespace", "arrow",
    "macro", "variable", "struct_toplevel", "struct_typedef", "enum_toplevel",
    "enumerator", "variable_toplevel", "function_toplevel",
    "type_alias_toplevel", "decorator", "variable_assignment",
}

# Slots the edge extractors and other passes look up by name.
EDGE_SLOTS = {
    "call", "method_call", "optional_call", "new", "scoped_call",
    "instantiate", "instantiate_call", "instantiate_new", "annotate",
    "require", "export",
    "inherits", "import", "import_from", "relative_import",
    "param", "param_value", "param_signature", "param_method",
    "param_abstract", "self_type",
}

KNOWN = SYMBOL_SLOTS | EDGE_SLOTS


def test_every_query_key_is_a_slot_the_parser_runs():
    from indexer.languages import LANGUAGE_QUERIES

    unknown = {}
    for language, queries in LANGUAGE_QUERIES.items():
        bad = sorted(set(queries) - KNOWN)
        if bad:
            unknown[language] = bad
    assert not unknown, (
        "these query names are never looked up, so the queries silently match "
        f"nothing: {unknown}"
    )


def test_kind_list_covers_the_toplevel_variants():
    """A `_toplevel` key only does something if the kind list asks for it."""
    import inspect

    from indexer.parser import CodeParser

    src = inspect.getsource(CodeParser._parse_with_queries)
    requested = set(re.findall(r'\(\s*"[a-z_]+"\s*,\s*"([a-z_]+)"\s*\)', src))
    assert {"struct_toplevel", "enumerator", "variable_toplevel"} <= requested, (
        f"kind list is missing top-level slots: {requested}"
    )


@pytest.mark.parametrize(
    "language,key",
    [("c", "macro"), ("lua", "function"), ("csharp", "param"),
     ("kotlin", "param"), ("php", "param_type")],
)
def test_named_queries_extract_something(language, key, tmp_path):
    """A live slot on a real file must actually produce its symbol."""
    import textwrap

    from indexer.parser import CodeParser
    from indexer.languages import LANGUAGE_QUERIES

    samples = {
        "c": (b"#define MAX 10\n#define MIN(a) (a)\n", {"MAX", "MIN"}),
        "lua": (b"function top() return 1 end\n", {"top"}),
        "csharp": (b"class A { void M(Widget w) { w.Go(); } }\n", {"w"}),
        "kotlin": (b"class A { fun m(w: Widget) { w.go() } }\n", {"w"}),
        "php": (b"<?php function f(Widget $w) { $w->go(); }\n", {"w"}),
    }
    if language not in LANGUAGE_QUERIES:
        pytest.skip(f"{language} has no query file")
    src, expected = samples[language]
    filename = {"c": "a.c", "lua": "a.lua", "csharp": "a.cs",
                "kotlin": "a.kt", "php": "a.php"}[language]
    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    symbols, edges = parser.parse(src, filename)
    if key.startswith("param"):
        # Parameter and receiver types are edges, not symbols: the receiver is
        # recorded on a param_type edge.
        got = {e["target_receiver"] for e in edges if e["edge_type"] == "param_type"}
    else:
        got = {s["symbol_name"] for s in symbols}
    assert expected <= got, f"{language}.{key} produced {sorted(got)}"
