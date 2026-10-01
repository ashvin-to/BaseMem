"""PHP.

php had no query file, and the repository originally chosen for testing it
(guzzlehttp/guzzle) has a README-only default branch, so the language was never
actually exercised: 0 files, 0 symbols. Re-tested against symfony/http-kernel,
338 files.

Two things specific to this grammar:

  * `$w->go()` is a `member_call_expression`, not a `function_call_expression`
    wrapping a `member_access_expression`, so it needs its own query
  * the receiver must be captured as the bare variable name. Capturing the whole
    `object` node yields `$w`, while a parameter is recorded as `w`, so every
    lookup misses on the sigil

Field order also matters: a `simple_parameter` has `type` as child 0 and `name`
as child 1, so `name:` before `type:` is an impossible pattern.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

SRC = b"""<?php
namespace App;

class Widget extends Base implements Runner {
    private int $n = 0;

    public function __construct(int $n) { $this->n = $n; }

    public function go(): int { return $this->helper(); }

    private function helper(): int { return 1; }
}

function topLevel(Widget $w) {
    $w->go();
    plain();
    $v = new Widget();
    $v->go();
}

interface Runner { public function run(): void; }
trait Loggable { public function log() {} }
"""


def _parse(tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / "a.php").write_bytes(SRC)
    parser = CodeParser.for_file("a.php")
    assert parser is not None
    return parser.parse(SRC, "a.php")


def test_php_declarations_are_extracted(tmp_path):
    symbols, _edges = _parse(tmp_path)
    got = {s["symbol_name"] for s in symbols}
    for expected in ("Widget", "go", "helper", "topLevel", "Runner", "Loggable"):
        assert expected in got, f"{expected} missing from {sorted(got)}"


def test_php_types_a_parameter_and_a_new_expression(tmp_path):
    _symbols, edges = _parse(tmp_path)
    typed = {
        (e["target_receiver"], e["target_name"])
        for e in edges
        if e["edge_type"] in ("param_type", "instantiates")
    }
    assert ("w", "Widget") in typed, f"parameter not typed: {sorted(typed)}"
    assert ("v", "Widget") in typed, f"'new Widget()' not typed: {sorted(typed)}"


def test_php_receiver_has_no_dollar_sigil(tmp_path):
    """`$w->go()` records `w`, not `$w`, or the parameter lookup misses."""
    _symbols, edges = _parse(tmp_path)
    receivers = {e["target_receiver"] for e in edges if e["edge_type"] == "member_calls"}
    assert "w" in receivers, f"expected a bare receiver, got {sorted(receivers)}"
    assert not any(r.startswith("$") for r in receivers), (
        f"receiver kept its sigil: {sorted(receivers)}"
    )


def test_php_emits_no_duplicate_edges(tmp_path):
    """Two patterns matching one node must not store the call twice."""
    _symbols, edges = _parse(tmp_path)
    seen = set()
    for e in edges:
        if e["edge_type"] not in ("calls", "member_calls"):
            continue
        key = (e["edge_type"], e.get("from_name", ""), e.get("target_name", ""),
               e.get("target_receiver", ""), e.get("line_number", 0))
        assert key not in seen, f"duplicate edge: {key}"
        seen.add(key)


def test_php_inheritance(tmp_path):
    _symbols, edges = _parse(tmp_path)
    assert any(
        e["edge_type"] == "inherits" and e["target_name"] == "Base" for e in edges
    ), "extends Base produced no inherits edge"
