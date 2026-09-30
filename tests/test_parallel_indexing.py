"""Parallel indexing must produce exactly what serial indexing produces.

`index_project` farms read+parse out to a process pool and keeps the sqlite
writes serial. The risk is not that it is slow, it is that the two halves
disagree -- a worker inheriting a parent's parser cache, results arriving out of
order, or a file silently dropped on the pool path.

These assert identical output at several worker counts, on a project large
enough to cross the pool threshold and containing several languages so that
more than one parser is involved.
"""

import shutil
import sqlite3
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

POOL_MIN_FILES = 24


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "PoolProj"
    (root / "src").mkdir(parents=True)
    for i in range(20):
        (root / "src" / f"mod{i}.py").write_text(
            textwrap.dedent(f"""
            def helper_{i}(a, b):
                return a + b

            class Thing_{i}:
                def method(self):
                    return helper_{i}(1, 2)
            """)
        )
    for i in range(12):
        (root / "src" / f"thing{i}.js").write_text(
            f"function alpha{i}(x) {{ return x; }}\n"
            f"var app = {{}};\n"
            f"app.run = function () {{ return alpha{i}(1); }};\n"
        )
    (root / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    (root / "notes.md").write_text("# hello\n")
    return root


def _index(root, workers):
    from indexer.indexer import CodeIndexer

    db = root / ".basemem.code.db"
    for stale in root.glob(".basemem.code.db*"):
        stale.unlink()
    ix = CodeIndexer(str(root))
    try:
        ix.index_project(_max_workers=workers)
    finally:
        ix.close()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        symbols = con.execute(
            "SELECT file_path, symbol_name, symbol_type, start_line, content_hash "
            "FROM code_symbols ORDER BY file_path, symbol_name, start_line"
        ).fetchall()
        edges = con.execute(
            "SELECT file_path, from_name, to_name, edge_type, line_number "
            "FROM code_edges ORDER BY file_path, from_name, to_name, edge_type, line_number"
        ).fetchall()
        files = con.execute(
            "SELECT file_path, symbol_count FROM code_files ORDER BY file_path"
        ).fetchall()
    finally:
        con.close()
    return symbols, edges, files


def test_pool_threshold_is_reachable(project):
    from indexer.indexer import CodeIndexer

    ix = CodeIndexer(str(project))
    try:
        found = len(list(ix._discover_files(project)))
    finally:
        ix.close()
    assert found >= POOL_MIN_FILES, (
        f"fixture has {found} indexable files, below the pool threshold"
    )


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_parallel_output_matches_serial(project, workers):
    baseline = _index(project, 1)
    got = _index(project, workers)
    assert got[0] == baseline[0], (
        f"{len(got[0])} symbols vs {len(baseline[0])} at {workers} workers"
    )
    assert got[1] == baseline[1], (
        f"{len(got[1])} edges vs {len(baseline[1])} at {workers} workers"
    )
    assert got[2] == baseline[2], "code_files inventory differs"


def test_parallel_indexes_everything_the_serial_path_does(project):
    symbols, edges, files = _index(project, 4)
    assert len(symbols) > 50, f"only {len(symbols)} symbols indexed"
    assert len(edges) > 0, "no edges produced"
    # a python and a javascript symbol, to prove more than one parser ran
    names = {row[1] for row in symbols}
    assert any(n.startswith("helper_") for n in names), "python symbols missing"
    assert any(n.startswith("alpha") for n in names), "javascript symbols missing"
    assert any(n == "run" for n in names), "assigned js method missing"
