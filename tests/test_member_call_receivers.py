"""Kotlin and C++ member calls must carry a receiver and a type.

Both languages had a `method_call` query that captured the method name but never
the object being called on, so every call arrived with an empty `to_receiver`.
With no receiver there is nothing to type and nothing can resolve: kotlin showed
6.6% member-call resolution with only 3 of 9,908 unlinked calls having a
receiver at all.

C++ had a second, separate fault: its function name sits under a chain of
declarators, so `_find_named_child` returned nothing and *every* edge from a C or
C++ file landed with an empty `from_name`, which made `get_callers` return
nothing at all.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

KOTLIN = b"""class Widget {
    fun go() {
        helper()
    }
}

fun run(w: Widget) {
    val v = Widget()
    w.go()
    v.go()
}
"""

CPP = b"""class Widget {
public:
    void go() { helper(); }
};

void use(Widget w, const Helper* h) {
    w.go();
    h->go();
}
"""


def _parse(filename, src, tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    assert parser is not None, f"no parser for {filename}"
    return parser.parse(src, filename)


def _edge_types(edges):
    return [e for e in edges if e["edge_type"] in ("calls", "member_calls", "param_type")]


def test_kotlin_member_calls_carry_a_receiver(tmp_path):
    _syms, edges = _parse("a.kt", KOTLIN, tmp_path)
    member = [e for e in edges if e["edge_type"] == "member_calls"]
    assert member, "no member calls found"
    assert all(e["target_receiver"] for e in member), (
        f"member calls lost their receiver: {[e for e in member if not e['target_receiver']]}"
    )


def test_kotlin_types_a_variable_and_a_parameter(tmp_path):
    """`val v = Widget()` and `w: Widget` are the two ways kotlin names a type."""
    _syms, edges = _parse("a.kt", KOTLIN, tmp_path)
    typed = {
        (e["target_receiver"], e["target_name"])
        for e in edges
        if e["edge_type"] in ("param_type", "instantiates")
    }
    assert ("w", "Widget") in typed, f"parameter not typed: {sorted(typed)}"
    assert ("v", "Widget") in typed, f"val-assignment not typed: {sorted(typed)}"


def test_kotlin_member_calls_are_attributed_to_their_caller(tmp_path):
    _syms, edges = _parse("a.kt", KOTLIN, tmp_path)
    member = [e for e in edges if e["edge_type"] == "member_calls"]
    assert all(e["from_name"] == "run" for e in member), (
        f"expected caller 'run', got {[e['from_name'] for e in member]}"
    )


def test_cpp_member_calls_carry_a_receiver(tmp_path):
    _syms, edges = _parse("a.cpp", CPP, tmp_path)
    member = [e for e in edges if e["edge_type"] == "member_calls"]
    assert member, "no member calls found"
    assert all(e["target_receiver"] for e in member), (
        f"cpp member calls lost their receiver: {[e for e in member if not e['target_receiver']]}"
    )


def test_cpp_types_both_plain_and_pointer_parameters(tmp_path):
    _syms, edges = _parse("a.cpp", CPP, tmp_path)
    typed = {
        (e["target_receiver"], e["target_name"])
        for e in edges
        if e["edge_type"] == "param_type"
    }
    assert ("w", "Widget") in typed, f"plain parameter not typed: {sorted(typed)}"
    assert ("h", "Helper") in typed, f"'const Helper *h' not normalised: {sorted(typed)}"


def test_cpp_edges_are_attributed_to_their_caller(tmp_path):
    """Regression: the name lives under function_declarator, two levels down."""
    _syms, edges = _parse("a.cpp", CPP, tmp_path)
    call_edges = _edge_types(edges)
    assert call_edges
    assert all(e["from_name"] for e in call_edges), (
        f"unattributed edges: {[e for e in call_edges if not e['from_name']]}"
    )
