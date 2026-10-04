"""Bulk load drops and rebuilds the code_symbols indexes."""

import sqlite3

import pytest

from indexer.indexer import CodeIndexer
from indexer.schema import (
    CODE_SYMBOL_INDEXES,
    create_code_symbol_indexes,
    drop_code_symbol_indexes,
    ensure_code_schema,
)


def _index_names(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='code_symbols' AND sql IS NOT NULL"
        )
    }


def _expected_names():
    return {s.split()[5] for s in CODE_SYMBOL_INDEXES}


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_schema_defines_every_symbol_index(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    ensure_code_schema(conn)
    for name in _expected_names():
        assert name in _index_names(conn), f"{name} missing after ensure_code_schema"
    conn.close()


def test_drop_then_recreate_restores_all(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    ensure_code_schema(conn)
    before = _index_names(conn)
    assert before

    dropped = drop_code_symbol_indexes(conn)
    assert set(dropped) == before
    assert _index_names(conn) == set()

    create_code_symbol_indexes(conn)
    assert _index_names(conn) == before
    conn.close()


def test_index_project_restores_indexes(tmp_path):
    _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "class C:\n    def m(self):\n        return self.m()\n")
    ix = CodeIndexer(str(tmp_path))
    ix.index_project(_max_workers=1)

    assert _expected_names() <= _index_names(ix.conn)
    ix.close()


def test_indexes_restored_when_the_load_is_interrupted(tmp_path, monkeypatch):
    """Ctrl+C mid-load must not leave the db without indexes."""
    for i in range(3):
        _write(tmp_path, f"f{i}.py", f"def f{i}():\n    return {i}\n")
    ix = CodeIndexer(str(tmp_path))

    real = ix._index_file
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt("user hit ctrl-c")
        return real(*a, **k)

    # KeyboardInterrupt is not an Exception, so the per-file handler does not
    # swallow it and the finally block is the only thing that runs.
    monkeypatch.setattr(ix, "_index_file", boom)
    with pytest.raises(KeyboardInterrupt):
        ix.index_project(_max_workers=1)

    assert _expected_names() <= _index_names(ix.conn)
    ix.close()
