"""Index every corpus repo with BaseMem and report extraction + resolution stats.

Usage:
    venv/bin/python3 bench_corpus.py --repos /mnt/Storage/bmlangs/repos [--query]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from indexer.indexer import CODE_DB_FILENAME, CodeIndexer  # noqa: E402


def stats(db_path: Path) -> dict:
    import sqlite3

    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    sym = c.execute("SELECT count(*) FROM code_symbols").fetchone()[0]
    edge = c.execute("SELECT count(*) FROM code_edges").fetchone()[0]
    res = c.execute(
        "SELECT count(*) FROM code_edges WHERE coalesce(to_symbol_id,0)!=0").fetchone()[0]
    files = c.execute("SELECT count(*) FROM code_files").fetchone()[0]
    zero = c.execute("SELECT count(*) FROM code_files WHERE symbol_count=0").fetchone()[0]
    by_type = dict(c.execute(
        "SELECT symbol_type, count(*) FROM code_symbols GROUP BY 1 ORDER BY 2 DESC").fetchall())
    by_edge = dict(c.execute(
        "SELECT edge_type, count(*) FROM code_edges GROUP BY 1 ORDER BY 2 DESC").fetchall())
    c.close()
    return {
        "files": files, "symbols": sym, "edges": edge, "resolved": res,
        "zero_symbol_files": zero,
        "pct_resolved": round(100 * res / edge) if edge else 0,
        "by_type": by_type, "by_edge": by_edge,
        "db_bytes": db_path.stat().st_size,
    }


def orphans(ix: CodeIndexer, limit: int = 500) -> dict:
    """Dead-code candidates, with the count's trustworthiness made explicit.

    Two things make a naive count misleading, and both showed up in the first
    corpus run:

    - Test files are invoked by a reflection-based runner, so a symbol there with
      no static caller is not evidence of anything. go went 307 -> 15 once these
      were separated.
    - Reflection- and registration-heavy languages genuinely have hundreds of
      such symbols, so the result hits the LIMIT and the number is a floor, not
      a total. Eleven repos returned exactly 500/500, which is the cap talking,
      not a measurement.

    A count that hit the cap is reported as `at_least` rather than as a number.
    """
    from indexer.query_execute import run

    rows = run(ix, "MATCH (a:Function) WHERE NOT (a)<-[:calls]-() "
                   f"RETURN a.name, a.file LIMIT {limit}")
    if not rows:
        return {"total": 0, "test_files": 0, "non_test": 0, "capped": False, "sample": []}
    key = next(k for k in rows[0] if k.endswith("symbol_name"))
    fkey = next(k for k in rows[0] if k.endswith("file_path"))

    def is_test(f: str) -> bool:
        return any(p in f for p in ("_test.", "test_", ".test.", "/test/", "/tests/"))

    test = [r for r in rows if is_test(r[fkey])]
    real = [r for r in rows if not is_test(r[fkey])]
    capped = len(rows) >= limit
    out = {
        "total": len(rows),
        "test_files": len(test),
        "non_test": len(real),
        "capped": capped,
        "sample": [f"{r[key]} ({r[fkey]})" for r in real[:8]],
    }
    if capped:
        # the honest form: we stopped looking, so the real number is higher
        out["non_test_at_least"] = len(real)
        out["non_test"] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default="/mnt/Storage/bmlangs/repos")
    ap.add_argument("--only", default="", help="comma-separated language subset")
    ap.add_argument("--out", default="/mnt/Storage/bmlangs-report/corpus.json")
    ap.add_argument("--query", action="store_true", help="also run the dead-code query")
    ap.add_argument("--fresh", action="store_true", help="reindex even if a db exists")
    args = ap.parse_args()

    root = Path(args.repos)
    langs = sorted(p for p in root.iterdir() if p.is_dir())
    if args.only:
        keep = set(args.only.split(","))
        langs = [p for p in langs if p.name in keep]

    rows = []
    for d in langs:
        db = d / CODE_DB_FILENAME
        t0 = time.time()
        if not db.exists() or args.fresh:
            for stale in d.glob(CODE_DB_FILENAME + "*"):
                stale.unlink()
            ix = CodeIndexer(str(d))
            try:
                ix.index_project(_max_workers=4)
            finally:
                ix.close()
        elapsed = time.time() - t0
        row = {"lang": d.name, "index_seconds": round(elapsed, 2), **stats(db)}
        if args.query:
            ix = CodeIndexer(str(d))
            try:
                row["orphans"] = orphans(ix)
            except Exception as e:
                row["orphans"] = {"error": f"{type(e).__name__}: {e}"}
            finally:
                ix.close()
        rows.append(row)
        extra = ""
        if args.query and "error" not in row.get("orphans", {}):
            o = row["orphans"]
            n = o["non_test"] if not o["capped"] else f">={o['non_test_at_least']}"
            extra = f"  orphans {n}/{o['total']}" + (" (capped)" if o["capped"] else "")
        print(f"  {row['lang']:<12} {row['files']:>5} files {row['symbols']:>7,} sym "
              f"{row['pct_resolved']:>3}% resolved {elapsed:>6.1f}s{extra}")

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    tot = {
        "files": sum(r["files"] for r in rows),
        "symbols": sum(r["symbols"] for r in rows),
        "edges": sum(r["edges"] for r in rows),
        "resolved": sum(r["resolved"] for r in rows),
        "db_bytes": sum(r["db_bytes"] for r in rows),
    }
    pct = round(100 * tot["resolved"] / tot["edges"]) if tot["edges"] else 0
    print()
    print(f"  {len(rows)} repos  {tot['files']:,} files  {tot['symbols']:,} symbols  "
          f"{tot['edges']:,} edges  {pct}% resolved  db {tot['db_bytes'] / 2**30:.2f} GiB")
    print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())