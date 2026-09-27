"""Reproducible, dependency-free performance measurements for BaseMem.

The benchmark uses deterministic records and batched SQLite writes.  The 100,000
record profile is opt-in because it is intentionally a heavier local run.

Run the default profiles with::

    python -m benchmarks.memory_performance --output benchmark/memory-performance.json

Run the heavy profile explicitly with::

    python -m benchmarks.memory_performance --include-100k --output benchmark/memory-performance-100k.json
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from graph.engine import GraphEngine
from models import EdgeType, Node, NodeType
from storage.db import StorageManager
from storage.sessions import SessionManager

DEFAULT_SCALES = (1_000, 10_000)
ALL_SCALES = (1_000, 10_000, 100_000)


def deterministic_memories(count: int) -> list[Node]:
    """Generate identical memories for a given count, without UUIDs or clocks."""
    stamp = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    return [
        Node(
            id=f"bench-{index:07d}",
            title=f"Memory {index:07d} deterministic",
            content=f"deterministic record {index} searchable needle {index % 97} category {index % 7}",
            node_type=NodeType.FACT,
            keywords=["benchmark", "deterministic", f"bucket{index % 13}"],
            created_at=stamp,
            last_accessed=stamp,
            metadata={"benchmark": True, "bucket": index % 13, "kind": f"kind-{index % 7}"},
        )
        for index in range(count)
    ]


def _timed(operation: Callable[[], Any], _deadline: float | None = None) -> tuple[Any, float]:
    start = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - start


def populate(storage: StorageManager, memories: list[Node], batch_size: int = 1_000) -> None:
    """Bulk insert nodes and FTS rows in bounded transactions."""
    cursor = storage.connection.cursor()
    node_sql = """INSERT INTO nodes
        (id,title,content,node_type,keywords,embedding,weight,created_at,last_accessed,decay_score,metadata)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
    for start in range(0, len(memories), batch_size):
        rows = [
            (
                node.id,
                node.title,
                node.content,
                node.node_type.value,
                json.dumps(node.keywords),
                None,
                node.weight,
                node.created_at.isoformat(),
                node.last_accessed.isoformat(),
                node.decay_score,
                json.dumps(node.metadata),
            )
            for node in memories[start : start + batch_size]
        ]
        cursor.executemany(node_sql, rows)
        fts_rows = []
        for node in memories[start : start + batch_size]:
            row = cursor.execute("SELECT rowid FROM nodes WHERE id=?", (node.id,)).fetchone()
            fts_rows.append((row[0], node.id, node.title, node.content, " ".join(node.keywords)))
        cursor.executemany("INSERT INTO nodes_fts(rowid,id,title,content,keywords) VALUES (?,?,?,?,?)", fts_rows)
        storage.connection.commit()


def add_graph_edges(storage: StorageManager, memories: list[Node], batch_size: int = 1_000) -> None:
    cursor = storage.connection.cursor()
    stamp = "2026-01-01T00:00:00+00:00"
    for start in range(0, len(memories), batch_size):
        batch = memories[start : start + batch_size]
        rows = [
            (node.id, memories[(start + index + 1) % len(memories)].id, EdgeType.RELATED_TO.value, 1.0, 1.0, stamp, "{}") for index, node in enumerate(batch)
        ]
        cursor.executemany("INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?)", rows)
        storage.connection.commit()


def complexity_checks(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check that timed operations do not show an obvious quadratic size jump."""
    checks: list[dict[str, Any]] = []
    for metric in ("fts_search", "metadata_filter", "graph_traversal", "retrieval", "context_compilation"):
        points = [(row["count"], row[metric]["ms"]) for row in measurements if row.get(metric)]
        if len(points) < 2:
            continue
        small, large = points[0], points[-1]
        expected = max(large[0] / small[0], 1.0)
        observed = max(large[1] / max(small[1], 0.001), 1.0)
        checks.append({"metric": metric, "observed_growth": observed, "size_growth": expected, "quadratic_suspected": observed > expected**2 * 8})
    return checks


def run_profile(count: int, output: str | Path | None = None, deadline_seconds: float = 120.0) -> dict[str, Any]:
    """Run all requested measurements for one record count."""
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="basemem-perf-") as directory:
        db_path = Path(directory) / "memory.db"
        startup, startup_seconds = _timed(lambda: StorageManager(str(db_path)))
        memories = deterministic_memories(count)
        _, insert_seconds = _timed(lambda: populate(startup, memories))
        add_graph_edges(startup, memories)
        manager = SessionManager(startup)
        for node in memories[: min(12, count)]:
            manager.create_note("benchmark", "FACT", node.content, source="benchmark", confidence=1.0)
        query = "searchable needle 17"
        fts_result, fts_seconds = _timed(lambda: startup.search_nodes_fts(query, limit=10))
        filter_result, filter_seconds = _timed(
            lambda: startup.connection.execute("SELECT id FROM nodes WHERE metadata LIKE '%\"bucket\": 3%' LIMIT 100").fetchall()
        )
        graph = GraphEngine(startup)
        graph_result, graph_seconds = _timed(lambda: graph.get_neighbors(memories[0].id, depth=2))
        retrieval_result, retrieval_seconds = _timed(lambda: [startup.get_node(node_id) for node_id in fts_result])
        compiled, context_seconds = _timed(lambda: manager.compile_context("benchmark", "needle", result_limit=12))
        startup.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database_size_bytes = db_path.stat().st_size
        startup.connection.close()
        elapsed = time.perf_counter() - started
        if elapsed > deadline_seconds:
            raise TimeoutError(f"benchmark profile {count} exceeded {deadline_seconds}s")
        report = {
            "count": count,
            "insert": {"seconds": insert_seconds, "rows_per_second": count / insert_seconds},
            "fts_search": {"ms": fts_seconds * 1000, "results": len(fts_result)},
            "metadata_filter": {"ms": filter_seconds * 1000, "results": len(filter_result)},
            "graph_traversal": {"ms": graph_seconds * 1000, "results": len(graph_result)},
            "retrieval": {"ms": retrieval_seconds * 1000, "results": len(retrieval_result)},
            "context_compilation": {"ms": context_seconds * 1000, "sections": len(compiled.get("sections", {}))},
            "database_size_bytes": database_size_bytes,
            "startup": {"ms": startup_seconds * 1000},
            "bounded_seconds": deadline_seconds,
        }
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def run_benchmark(scales: tuple[int, ...] = DEFAULT_SCALES, output: str | Path | None = None) -> dict[str, Any]:
    measurements = [run_profile(count) for count in scales]
    report = {"schema": 1, "scales": list(scales), "measurements": measurements, "complexity_checks": complexity_checks(measurements)}
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-100k", action="store_true", help="also run the opt-in 100,000 profile")
    parser.add_argument("--output", type=Path, help="write the generated JSON artifact")
    args = parser.parse_args()
    print(json.dumps(run_benchmark(ALL_SCALES if args.include_100k else DEFAULT_SCALES, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
