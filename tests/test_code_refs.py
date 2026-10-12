"""Memory <-> code symbol links.

A decision should stay attached to the symbol it changed, including across a
rename or a move. That rests on body_hash being rename-invariant while still
discriminating a real change to the body.
"""

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "RefProj"
        (root / "pkg").mkdir(parents=True)
        yield root


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_body_hash_survives_rename_and_move(workspace):
    from indexer.indexer import CodeIndexer

    f = workspace / "pkg" / "core.js"
    _write(f, "export function originalName() { return 1 }\n")
    indexer = CodeIndexer(str(workspace))
    try:
        indexer.index_project(_max_workers=1)
        before = indexer.search_symbols("originalName")[0]
        assert before["body_hash"]

        f.unlink()
        _write(workspace / "pkg" / "entry.js", "export function renamedEntry() { return 1 }\n")
        indexer.sync_index()
        after = indexer.search_symbols("renamedEntry")[0]
        assert after["body_hash"] == before["body_hash"]
    finally:
        indexer.close()


def test_body_hash_changes_when_body_changes(workspace):
    from indexer.indexer import CodeIndexer

    f = workspace / "pkg" / "core.js"
    _write(f, "export function thing() { return 1 }\n")
    indexer = CodeIndexer(str(workspace))
    try:
        indexer.index_project(_max_workers=1)
        before = indexer.search_symbols("thing")[0]["body_hash"]
        _write(f, "export function thing() { return 99 }\n")
        indexer.sync_index()
        assert indexer.search_symbols("thing")[0]["body_hash"] != before
    finally:
        indexer.close()


def test_resolve_refs_captures_hash(workspace):
    from indexer.indexer import CodeIndexer

    _write(workspace / "pkg" / "core.js", "export function thing() { return 1 }\n")
    indexer = CodeIndexer(str(workspace))
    try:
        indexer.index_project(_max_workers=1)
        resolved = indexer.resolve_refs(["pkg/core.js::thing"])
        assert resolved[0][0] == "pkg/core.js"
        assert resolved[0][1] == "thing"
        assert resolved[0][2], "a resolved ref must carry a hash for rename survival"
    finally:
        indexer.close()


def test_note_link_roundtrip_and_rename_survival(workspace, tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setenv("BASEMEM_DB_PATH", str(tmp_path / "mem.db"))
    spec = importlib.util.spec_from_file_location(
        "bm_server_refs", Path(__file__).resolve().parents[1] / "mcp_server" / "server.py"
    )
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server.get_db_path()

    f = workspace / "pkg" / "core.js"
    _write(f, "export function originalName() { return 1 }\n")
    server.code_init(projectRoot=str(workspace))
    server.logInteraction(
        topic="RefProj",
        decision="originalName is the entry point.",
        symbols="pkg/core.js::originalName",
        projectRoot=str(workspace),
    )

    def notes(ref):
        out = server.code_refs(action="notes", ref=ref, projectRoot=str(workspace))
        return [ln for ln in out.splitlines() if "entry point" in ln]

    assert notes("pkg/core.js::originalName"), "linked note must be findable before any edit"

    f.unlink()
    _write(workspace / "pkg" / "entry.js", "export function renamedEntry() { return 1 }\n")
    server.code_sync(projectRoot=str(workspace))
    assert notes("pkg/entry.js::renamedEntry"), "note must survive a rename and a move"

    _write(workspace / "pkg" / "entry.js", "export function renamedEntry() { return 99 }\n")
    server.code_sync(projectRoot=str(workspace))
    assert not notes("pkg/entry.js::renamedEntry"), "a real body change should drop the link"
