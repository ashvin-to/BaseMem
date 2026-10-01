"""Query files for csharp, ruby, r and swift.

These four had none, so the indexer used the generic structure pass. Measured on
real repositories that meant:

  csharp  959 files, 1398 symbols, 0 call edges
  ruby    183 files,  287 symbols, 0 call edges
  r       366 files, 1890 symbols, 0 call edges
  swift   890 files, 2426 symbols, 10 call edges

so `get_callers` and `code_trace` returned nothing for all of them.

Note on r: its symbol count *falls* from 1890 to about 1196, and that is a fix.
The generic path was inventing symbols all literally named `function` -- 307 of
them across 60 ggplot2 files -- by matching the keyword. Those were noise.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

CSHARP = b"""namespace Demo {
    public class Widget : Base {
        private int _n;
        public Widget(int n) { _n = n; }
        public void Go() { Helper(); other.Run(); }
        private int Helper() { return _n; }
    }
    public enum E { A, B }
}
"""

RUBY = b"""class Widget < Base
  def go; helper(); other.run; end
  def self.make; new(1); end
end
module M
end
"""

R = b"""go <- function() { helper(); obj$run() }
helper <- function() { 1 }
print.foo <- function(x) { x }
"""

SWIFT = b"""class Widget: Base {
    var n: Int = 0
    func go() -> Int { return helper() }
}
func helper() -> Int { return 1 }
struct P { var x: Int }
protocol Q {}
"""


def _parse(filename, src, tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    assert parser is not None, f"no parser for {filename}"
    symbols, edges = parser.parse(src, filename)
    return symbols, edges


def _names(symbols):
    return {s["symbol_name"] for s in symbols}


def _calls(edges):
    return [e for e in edges if e["edge_type"] in ("calls", "member_calls")]


def test_csharp_produces_a_call_graph(tmp_path):
    symbols, edges = _parse("a.cs", CSHARP, tmp_path)
    names = _names(symbols)
    assert {"Widget", "Helper", "E"} <= names, sorted(names)
    calls = _calls(edges)
    assert calls, "csharp produced no calls"
    targets = {c["target_name"] for c in calls}
    assert "Helper" in targets, f"free call missing: {sorted(targets)}"
    member = [c for c in calls if c["edge_type"] == "member_calls"]
    assert member, "no member calls"
    assert all(c["target_receiver"] for c in member), (
        f"csharp member calls lost the receiver: {member}"
    )


def test_ruby_produces_a_call_graph(tmp_path):
    symbols, edges = _parse("a.rb", RUBY, tmp_path)
    names = _names(symbols)
    assert {"Widget", "go", "make", "M"} <= names, sorted(names)
    targets = {c["target_name"] for c in _calls(edges)}
    assert "helper" in targets, f"ruby call missing: {sorted(targets)}"
    assert any(e["edge_type"] == "inherits" and e["target_name"] == "Base" for e in edges)


def test_r_functions_including_s3_methods(tmp_path):
    symbols, edges = _parse("a.r", R, tmp_path)
    names = _names(symbols)
    # `print.foo <- function()` has an extract_operator on the left, so a query
    # matching only a plain identifier loses every S3 method.
    assert {"go", "helper", "print.foo"} <= names, sorted(names)
    targets = {c["target_name"] for c in _calls(edges)}
    assert "helper" in targets, f"r call missing: {sorted(targets)}"
    assert any(c["edge_type"] == "member_calls" for c in _calls(edges)), (
        "the obj$run() pipe produced no member call"
    )


def test_swift_produces_a_call_graph(tmp_path):
    symbols, edges = _parse("a.swift", SWIFT, tmp_path)
    names = _names(symbols)
    assert {"Widget", "go", "helper", "Q"} <= names, sorted(names)
    targets = {c["target_name"] for c in _calls(edges)}
    assert "helper" in targets, f"swift call missing: {sorted(targets)}"


@pytest.mark.parametrize(
    "filename,src,forbidden",
    [
        ("a.cs", CSHARP, "function"),
        ("a.rb", RUBY, "function"),
        ("a.r", R, "function"),
        ("a.swift", SWIFT, "function"),
    ],
)
def test_no_symbol_is_named_after_the_keyword(tmp_path, filename, src, forbidden):
    """The generic path invented symbols called `function`, 307 times in 60 files.

    A query file must never reproduce that: no symbol may be named for the
    keyword that introduces it.
    """
    symbols, _edges = _parse(filename, src, tmp_path)
    assert forbidden not in _names(symbols), f"{filename} produced a symbol named {forbidden!r}"
