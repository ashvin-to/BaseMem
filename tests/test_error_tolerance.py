"""A file with a localised parse error must still be indexed.

`_parse_with_queries` used to return nothing at all whenever the tree had any
error, so a single unrecognised token voided every symbol in the file. In zlib
that is `#define local static` -- 50% of the repository was discarded, including
all 83KB of deflate.c, which has 34 functions.

The fix counts errored *top-level* children rather than bytes, because once
tree-sitter loses sync it swallows a large span into a single ERROR node. In
deflate.c that node covers 70% of the bytes but is 1 of 50 top-level children,
and the other 49 parse perfectly.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

# `local` is a zlib macro for `static`; the C grammar has never heard of it.
ZSLIB = b"""local int deflate_stored(deflate_state *s, int flush) {
    return 0;
}

int deflateInit2(z_streamp strm, int level) {
    return 0;
}

local void putShortMSB(uInt b) {
    return;
}
"""

BROKEN = b"\x00\x01\x02 not source at all ((( \xff\xfe"


def test_file_with_unknown_macro_still_yields_symbols(tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / "a.c").write_bytes(ZSLIB)
    parser = CodeParser.for_file("a.c")
    tree = parser.parser.parse(ZSLIB)
    assert tree.root_node.has_error, "fixture should contain a parse error"

    symbols, _edges = parser.parse(ZSLIB, "a.c")
    names = {s["symbol_name"] for s in symbols}
    assert names, "a localised error voided the whole file"
    assert "deflateInit2" in names, f"expected the clean function, got {sorted(names)}"


def test_genuinely_broken_file_is_still_skipped(tmp_path):
    """Error tolerance must not turn garbage into a symbol."""
    from indexer.parser import CodeParser, _too_broken_to_index

    (tmp_path / "b.c").write_bytes(BROKEN)
    parser = CodeParser.for_file("b.c")
    root = parser.parser.parse(BROKEN).root_node
    assert _too_broken_to_index(root), "unparseable input should be rejected"
    symbols, _edges = parser.parse(BROKEN, "b.c")
    assert not symbols


def test_byte_share_does_not_decide(tmp_path):
    """The regression this guards, in the shape deflate.c actually has.

    One errored *top-level* child among several good ones must not disqualify the
    file. Judging by bytes instead is what this replaced: once tree-sitter loses
    sync a single ERROR node swallows a large span, so a byte share reports a
    mostly-unparseable file when almost all of it is fine.
    """
    from indexer.parser import CodeParser, _too_broken_to_index

    src = b"""#define local static
@@@ broken top level @@@
int alpha(void) { return 1; }
int beta(void) { return 2; }
int gamma(void) { return 3; }
int delta(void) { return 4; }
"""
    (tmp_path / "c.c").write_bytes(src)
    parser = CodeParser.for_file("c.c")
    root = parser.parser.parse(src).root_node

    errored = [c for c in root.children if c.type == "ERROR"]
    assert errored, "fixture should produce a top-level ERROR child"
    assert not _too_broken_to_index(root), (
        "one errored top-level child out of six must not disqualify the file"
    )

    symbols, _edges = parser.parse(src, "c.c")
    assert {"alpha", "beta", "gamma", "delta"} <= {s["symbol_name"] for s in symbols}
