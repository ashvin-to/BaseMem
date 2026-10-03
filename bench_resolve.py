"""Measure the resolve pass on a slice of the kernel, fast.

Full-kernel resolution takes ~220s and 2.7 GiB, which is too slow to iterate on.
This slices the already-indexed DB down to a fixed number of unresolved edges and
times just the pass, so a candidate fix can be judged in a couple of minutes.

Usage:
    venv/bin/python3 bench_resolve.py --limit 60000 [--by-edges]
"""

import argparse
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

SRC = "/mnt/Storage/basemem-bench/linux/.basemem.code.db"


def build_slice(dest: Path, limit: int, by_edges: bool) -> sqlite3.Connection:
    """Copy the schema plus a slice of symbols/edges into a fresh db."""
    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    src = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)

    ddl = [r[0] for r in src.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'code_symbols_fts_%'"
    )]
    for stmt in ddl:
        if "VIRTUAL TABLE" in stmt:
            continue
        conn.execute(stmt)

    if by_edges:
        # one file per edge sample, then every symbol in those files
        edges = src.execute(
            "SELECT file_path FROM code_edges WHERE coalesce(to_symbol_id,0)=0 "
            "AND to_name IS NOT NULL AND to_name!='' LIMIT ?", (limit,)
        ).fetchall()
        files = sorted({r[0] for r in edges})
    else:
        files = [r[0] for r in src.execute(
            "SELECT DISTINCT file_path FROM code_symbols LIMIT ?", (limit,)
        )]

    conn.executemany(
        "INSERT OR IGNORE INTO code_projects (id, root_path, name) VALUES ('linux','/x','linux')",
        [],
    )
    marks = ",".join("?" * len(files))
    for tbl, cols in (
        ("code_symbols", "project_id,file_path,symbol_name,symbol_type,language,kind,start_line,"
                         "end_line,start_col,end_col,signature,docstring,content_hash,body_hash"),
        ("code_edges", "project_id,from_symbol_id,to_symbol_id,from_name,to_name,to_receiver,"
                       "edge_type,file_path,line_number"),
        ("code_files", "project_id,file_path,mtime,size,symbol_count"),
    ):
        q = ",".join("?" * len(cols.split(",")))
        for i in range(0, len(files), 500):
            chunk = files[i:i + 500]
            rows = src.execute(
                f"SELECT {cols} FROM {tbl} WHERE file_path IN ({','.join('?' * len(chunk))})", chunk
            )
            conn.executemany(f"INSERT OR IGNORE INTO {tbl} ({cols}) VALUES ({q})", rows)
    conn.commit()

    n_sym = conn.execute("SELECT count(*) FROM code_symbols").fetchone()[0]
    n_edge = conn.execute("SELECT count(*) FROM code_edges").fetchone()[0]
    n_open = conn.execute("SELECT count(*) FROM code_edges WHERE coalesce(to_symbol_id,0)=0").fetchone()[0]
    src.close()
    print(f"  slice: {len(files):,} files  {n_sym:,} symbols  {n_edge:,} edges  "
          f"({n_open:,} unresolved)")
    return conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    ap.add_argument("--by-edges", action="store_true",
                    help="sample by unresolved edges instead of by file")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--profile", action="store_true")
    args = ap.parse_args()

    import indexer.indexer as I
    from indexer.indexer import CodeIndexer

    tmp = Path(tempfile.mkdtemp()) / "slice"
    tmp.mkdir(parents=True)
    for _ in range(args.repeat):
        for f in tmp.glob("*.db*"):
            f.unlink()
        conn = build_slice(tmp / ".basemem.code.db", args.limit, args.by_edges)
        conn.close()

        ix = CodeIndexer(str(tmp))
        ix.project_id = "linux"   # slice rows carry the source project id
        t = time.time()
        maps = ix._build_resolution_maps()
        t_maps = time.time() - t
        del maps

        if args.profile:
            import cProfile, pstats, io
            pr = cProfile.Profile(); pr.enable()
            t = time.time(); ix._resolve_cross_file_references(); t_res = time.time() - t
            pr.disable()
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(12)
            print("\n".join(s.getvalue().splitlines()[4:22]))
        else:
            t = time.time()
            ix._resolve_cross_file_references()
            t_res = time.time() - t
        pass_only = t_res - t_maps
        n_open = ix.conn.execute(
            "SELECT count(*) FROM code_edges WHERE coalesce(to_symbol_id,0)=0").fetchone()[0]
        print(f"  maps {t_maps:6.2f}s | pass {pass_only:6.2f}s | resolve {t_res:6.2f}s "
              f"| still open {n_open:,}")
        ix.close()
    shutil.rmtree(tmp.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
