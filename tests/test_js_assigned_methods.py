"""JS/TS: functions assigned to properties must be indexed.

`obj.method = function () {}` and `obj.method = () => {}` are the dominant
idioms in CommonJS and prototype-style JavaScript. Before these queries existed,
express's `lib/` produced 2 symbols from 13,953 bytes while still emitting 113
call edges -- the calls were recorded but their targets were invisible.

Two subtleties this guards, both of which fail silently:

  * the function is anonymous, so it can only be named by the property it is
    assigned to; a query matching the function node alone captures nothing
  * `@symbol` must sit on the `pair`, not the enclosing `object`. The parser
    dedupes symbols by byte range, so with `@symbol` on the object every
    function-valued key in one literal collapses into a single symbol.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

SOURCE = b"""var express = require('express');

var app = function() {};

app.use = function(fn) { return fn; };
app.lazyrouter = function() {};
app.handle = (req, res) => { app.use(req, res); };

var bare = () => 1;

function createApplication() { return app; }

module.exports = { init: function() {}, close: () => {} };
"""

EXPECTED = {
    "use", "lazyrouter", "handle",   # obj.prop = function / arrow
    "init", "close",                 # function-valued keys in one object literal
    "createApplication",             # plain declaration
    "bare",                          # var x = () => {}
}


def _names(lang, filename):
    from indexer.parser import CodeParser

    parser = CodeParser.for_file(filename)
    symbols, _edges = parser.parse(SOURCE, filename)
    return {s["symbol_name"] for s in symbols}


@pytest.mark.parametrize(
    "lang,filename",
    [("javascript", "a.js"), ("typescript", "a.ts"), ("tsx", "a.tsx")],
)
def test_assigned_methods_are_indexed(lang, filename, tmp_path):
    (tmp_path / filename).write_bytes(SOURCE)
    assert _names(lang, filename) == EXPECTED


def test_every_key_in_one_object_literal_survives(tmp_path):
    """Regression: @symbol on the object made the parser's range dedupe eat all
    but the first key."""
    src = b"module.exports = { alpha: function() {}, beta: function() {}, gamma: () => {} };"
    (tmp_path / "x.js").write_bytes(src)
    from indexer.parser import CodeParser

    parser = CodeParser.for_file("x.js")
    symbols, _ = parser.parse(src, "x.js")
    names = {s["symbol_name"] for s in symbols}
    assert {"alpha", "beta", "gamma"} <= names, f"only got {sorted(names)}"


def test_assigned_methods_are_typed_as_methods(tmp_path):
    (tmp_path / "x.js").write_bytes(SOURCE)
    from indexer.parser import CodeParser

    parser = CodeParser.for_file("x.js")
    symbols, _ = parser.parse(SOURCE, "x.js")
    by_name = {s["symbol_name"]: s["symbol_type"] for s in symbols}
    assert by_name.get("use") == "method"
    assert by_name.get("createApplication") == "function"
