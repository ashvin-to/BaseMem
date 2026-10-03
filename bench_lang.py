"""Report per-repo symbol and edge-resolution stats for a language under test.

Usage: venv/bin/python3 bench_lang.py lua [nim go ...]
"""

import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

SRC = "/tmp/bmlangs/repos"


def stats(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sym = c.execute("SELECT count(*) FROM code_symbols").fetchone()[0]
    edge = c.execute("SELECT count(*) FROM code_edges").fetchone()[0]
    res = c.execute("SELECT count(*) FROM code_edges WHERE coalesce(to_symbol_id,0)!=0").fetchone()[0]
    files = c.execute("SELECT count(*) FROM code_files").fetchone()[0]
    zero = c.execute(
        "SELECT count(*) FROM code_files WHERE symbol_count=0").fetchone()[0]
    by_type = dict(c.execute(
        "SELECT symbol_type, count(*) FROM code_symbols GROUP BY 1 ORDER BY 2 DESC").fetchall())
    by_edge = dict(c.execute(
        "SELECT edge_type, count(*) FROM code_edges GROUP BY 1 ORDER BY 2 DESC").fetchall())
    c.close()
    return files, sym, edge, res, zero, by_type, by_edge


def main():
    for lang in sys.argv[1:]:
        src = Path(SRC) / lang
        if not src.is_dir():
            print(f"  {lang}: MISSING {src}")
            continue
        tmp = Path(tempfile.mkdtemp()) / lang
        shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(".git"))
        from indexer.indexer import CodeIndexer
        ix = CodeIndexer(str(tmp))
        t = time.time()
        r = ix.index_project(_max_workers=4)
        el = time.time() - t
        files, sym, edge, res, zero, bt, be = stats(ix.db_path)
        ix.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)
        pct = 100 * res // max(edge, 1)
        print(f"\n  {lang}: {files} files, {sym:,} sym, {edge:,} edges, "
              f"{pct}% resolved, {el:.2f}s")
        if zero:
            print(f"    files with 0 symbols: {zero}")
        print(f"    symbols: {bt}")
        print(f"    edges:   {be}")


if __name__ == "__main__":
    main()
