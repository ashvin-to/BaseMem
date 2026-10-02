"""Trained models, and the last three languages off the generic path.

Two separate things, both found by indexing a real repository.

Artifacts: DevTwin keeps a `models/` directory, and `.pkl` is one of only two
model extensions the language pack actually maps, so every checkpoint was being
read into memory and handed to tree-sitter on each index. The rest -- .keras,
.h5, .pt, .onnx, .safetensors, .bin, .npy -- were skipped only by accident of the
pack not mapping them, which is not a guarantee.

Languages: bash, lua and objc were the last three without a query file.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")


# ── model artifacts ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ext", [".pkl", ".pbtxt", ".keras", ".h5", ".pt", ".pth", ".onnx",
            ".safetensors", ".tflite", ".npy", ".npz", ".parquet", ".ckpt",
            ".gguf", ".msgpack", ".mdb"]
)
def test_model_artifacts_are_not_indexed(ext):
    from indexer.parser import CodeParser
    from indexer.indexer import SKIP_EXTENSIONS

    assert CodeParser.supported_extension(ext) is False, f"{ext} would be read"
    assert ext in SKIP_EXTENSIONS, f"{ext} missing from the discovery skip list"


@pytest.mark.parametrize("ext", [".py", ".js", ".ts", ".rs", ".go", ".java",
                                 ".yaml", ".toml", ".tf", ".sql", ".c", ".cpp"])
def test_real_source_is_still_indexed(ext):
    from indexer.parser import CodeParser

    assert CodeParser.supported_extension(ext) is True, f"{ext} is now skipped"


def test_artifact_file_is_not_discovered(tmp_path):
    from indexer.indexer import CodeIndexer

    root = tmp_path / "ModelProj"
    (root / "models").mkdir(parents=True)
    (root / "models" / "best.pkl").write_bytes(b"\x80\x04\x95binaryblob")
    (root / "app.py").write_text("def run():\n    return 1\n")
    ix = CodeIndexer(str(root))
    try:
        found = {p.name for p in ix._discover_files(root)}
    finally:
        ix.close()
    assert "best.pkl" not in found, "the model artifact was discovered"
    assert "app.py" in found


# ── bash / lua / objc ────────────────────────────────────────────────

LUA = b"""local M = {}
function M.new(n) return M end
function M:go() return self.helper() end
function M:helper() return 1 end
function top(x) return M.new(x) end
"""

OBJC = b"""@interface Widget : NSObject
- (void)go;
@end
@implementation Widget
- (void)go { [self helper]; helper(); }
- (int)helper { return 1; }
@end
"""

BASH = b"""#!/bin/bash
top() { local a=1; helper; }
helper() { return 0; }
top
"""


def _parse(filename, src, tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    assert parser is not None, f"no parser for {filename}"
    return parser.parse(src, filename)


def test_lua_covers_every_declaration_form(tmp_path):
    """Regression: `function_signature` is not an extractor slot.

    The parser only ever runs the slot names in its kind list, so a query filed
    under `function_signature` is never evaluated. That silently took a real
    20KB file from 31 symbols to 0 and dropped lua's resolution to 9.7%.
    """
    symbols, _edges = _parse("a.lua", LUA, tmp_path)
    got = {s["symbol_name"] for s in symbols}
    assert {"new", "go", "helper", "top"} <= got, f"missing from {sorted(got)}"


def test_lua_method_calls_carry_a_receiver(tmp_path):
    _symbols, edges = _parse("a.lua", LUA, tmp_path)
    member = [e for e in edges if e["edge_type"] == "member_calls"]
    assert member, "no lua member calls"
    assert all(e["target_receiver"] for e in member), (
        f"lua member calls lost the receiver: {member}"
    )


def test_objc_message_sends(tmp_path):
    symbols, edges = _parse("a.m", OBJC, tmp_path)
    got = {s["symbol_name"] for s in symbols}
    assert {"Widget", "go", "helper"} <= got, f"missing from {sorted(got)}"
    # `[self helper]` is a message_expression, not a plain call.
    assert any(
        e["edge_type"] == "member_calls" and e["target_receiver"] == "self"
        for e in edges
    ), "the ObjC message send produced no member call"
    assert any(e["edge_type"] == "inherits" and e["target_name"] == "NSObject"
               for e in edges), "the superclass produced no inherits edge"


def test_bash_functions_are_extracted(tmp_path):
    symbols, edges = _parse("a.sh", BASH, tmp_path)
    got = {s["symbol_name"] for s in symbols}
    assert {"top", "helper"} <= got, f"missing from {sorted(got)}"
    targets = {e["target_name"] for e in edges if e["edge_type"] == "calls"}
    assert "helper" in targets, f"the call to helper was missed: {sorted(targets)}"
