"""Auto-indexing from a query must stay bounded and must not wedge the server."""

import subprocess
import sys

import pytest

from indexer.indexer import CodeIndexer
from indexer.lifecycle import (
    MAX_AUTO_INDEX_FILES,
    AutoIndexRefused,
    open_or_create_index,
)


def _tree(tmp_path, n):
    for i in range(n):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")


def test_small_tree_is_indexed_implicitly(tmp_path):
    _tree(tmp_path, 3)
    ix = open_or_create_index(str(tmp_path), max_workers=1)
    try:
        assert ix.conn.execute("SELECT count(*) FROM code_symbols").fetchone()[0] == 3
    finally:
        ix.close()


def test_oversized_tree_is_refused_not_indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "indexer.lifecycle.MAX_AUTO_INDEX_FILES", 5
    )
    _tree(tmp_path, 20)
    with pytest.raises(AutoIndexRefused) as e:
        open_or_create_index(str(tmp_path), max_workers=1)
    msg = str(e.value)
    assert "mem code init" in msg, msg
    assert not (tmp_path / ".basemem.code.db").exists(), "must not have indexed"


def test_refusal_message_reports_the_real_count(tmp_path, monkeypatch):
    monkeypatch.setattr("indexer.lifecycle.MAX_AUTO_INDEX_FILES", 5)
    _tree(tmp_path, 7)
    with pytest.raises(AutoIndexRefused) as e:
        open_or_create_index(str(tmp_path), max_workers=1)
    assert "7" in str(e.value)


def test_existing_index_is_reused_without_rebuilding(tmp_path):
    _tree(tmp_path, 2)
    first = open_or_create_index(str(tmp_path), max_workers=1)
    first.close()
    stamp = (tmp_path / ".basemem.code.db").stat().st_mtime_ns
    second = open_or_create_index(str(tmp_path), max_workers=1)
    try:
        assert (tmp_path / ".basemem.code.db").stat().st_mtime_ns == stamp
    finally:
        second.close()


def test_parallel_build_runs_in_a_subprocess(tmp_path, monkeypatch):
    """The caller must not fork a pool; that deadlocked the MCP server."""
    _tree(tmp_path, 30)
    seen = {}
    real_run = subprocess.run

    def spy(cmd, **kw):
        seen["cmd"] = cmd
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    ix = open_or_create_index(str(tmp_path), max_workers=4)
    try:
        assert seen, "expected the index to be built via subprocess.run"
        assert seen["cmd"][1] == "-c"
        assert seen["cmd"][0] == sys.executable
        assert ix.conn.execute("SELECT count(*) FROM code_symbols").fetchone()[0] == 30
    finally:
        ix.close()


def test_index_exists_after_subprocess_build(tmp_path, monkeypatch):
    _tree(tmp_path, 30)
    monkeypatch.setattr(
        "indexer.lifecycle._PARALLEL_MIN_FILES", 1, raising=False
    )
    import indexer.lifecycle as lc
    monkeypatch.setattr(lc, "_PARALLEL_MIN_FILES", 1)
    ix = open_or_create_index(str(tmp_path), max_workers=4)
    try:
        assert CodeIndexer(str(tmp_path)).db_path
        assert ix.conn.execute("SELECT count(*) FROM code_symbols").fetchone()[0] > 0
    finally:
        ix.close()


def test_subprocess_failure_surfaces_the_error(tmp_path, monkeypatch):
    _tree(tmp_path, 30)

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "boom: index broke\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(RuntimeError) as e:
        open_or_create_index(str(tmp_path), max_workers=4)
    assert "index broke" in str(e.value)


def test_limit_default_is_sane():
    assert 1_000 <= MAX_AUTO_INDEX_FILES <= 200_000