"""Deterministic labeled memory retrieval benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sqlite3
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from storage.db import StorageManager
from storage.sessions import SessionManager

TOPIC = "memory-benchmark"
RUN_COMMAND = "uv run python -m benchmarks.memory_benchmark --output benchmark/baseline.json --repeats 3"

NOTES = [
    ("fact", "The project uses SQLite for durable local memory because it is embedded and requires no server.", "SQLite storage choice"),
    ("fact", "Authentication uses signed access tokens and rotates refresh tokens; "
     "authorization is checked at the API boundary.", "Authentication and authorization flow"),
    ("fact", "Redis is reserved for production caching and is intentionally out of scope for local development.", "Redis development scope"),
    ("fact", "For the flaky test, rerun the affected test in isolation before changing shared fixtures.", "Flaky-test workaround"),
    ("fact", "The previous database was PostgreSQL, but the current release migrated to SQLite for local-first operation.", "Previous database history"),
    ("fact", "The codebase is organized into storage, graph, indexer, CLI, MCP server, and frontend modules.", "Module architecture"),
    ("fact", "Deployment is discovered from the release manifest, which names the container image and target environment.", "Deployment discovery"),
    ("fact", "The API server exposes Flask routes and delegates code intelligence to the tree-sitter indexer.", "API and indexer relationship"),
    ("fact", "Notes are persisted in a SQLite table and indexed by an FTS5 virtual table for keyword retrieval.", "Persistence and FTS indexing"),
    ("fact", "Graph edges represent relationships between notes and support bounded neighborhood traversal.", "Graph relationships"),
    ("fact", "The CLI exposes commands for creating, reading, searching, and pinning notes.", "CLI note operations"),
    ("fact", "The MCP server provides public tools for memory recall and durable note creation.", "MCP memory tools"),
    ("fact", "The frontend renders a knowledge graph and a project code-intelligence view.", "Frontend views"),
    ("fact", "Configuration uses environment variables with local defaults and validates required values.", "Configuration conventions"),
    ("fact", "Session state tracks the active agent, last activity, and durable handoff context.", "Session state"),
    ("fact", "Code indexing parses source files into symbols and stores searchable symbol metadata.", "Code indexing workflow"),
    ("fact", "FTS5 ranking is deterministic for a fixed database and query, while wall-clock latency varies by environment.", "Ranking and latency caveat"),
    ("fact", "The project supports tests with pytest and uses temporary SQLite databases in storage tests.", "Testing conventions"),
    ("fact", "A release is considered ready when focused tests and the full test suite pass in the target environment.", "Release readiness"),
    ("fact", "The benchmark must report relevance, ranking, latency, and context size without changing retrieval code.", "Benchmark principles"),
]

QUERY_ROWS = [
    ("sqlite-choice", "Which database did the project choose for local durable storage?", "SQLite storage choice"),
    ("auth", "How are access tokens and API authorization handled?", "Authentication and authorization flow"),
    ("redis-dev", "Is Redis required for local development work?", "Redis development scope"),
    ("flaky-test", "What should I try when a test is flaky?", "Flaky-test workaround"),
    ("previous-db", "Which database did the project use before the current release?", "Previous database history"),
    ("module-architecture", "What are the main modules in the codebase?", "Module architecture"),
    ("deployment", "Where does the project discover deployment targets and images?", "Deployment discovery"),
]


@dataclass(frozen=True)
class Query:
    identifier: str
    text: str
    relevant_title: str


QUERIES: list[Query] = [Query(*row) for row in QUERY_ROWS]


def dataset_digest() -> str:
    payload = json.dumps({"notes": NOTES, "queries": [asdict(query) for query in QUERIES]}, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def build_fixture(db_path: str) -> tuple[StorageManager, dict[str, int]]:
    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    relevant: dict[str, int] = {}
    for kind, content, title in NOTES:
        note = manager.add_note("", TOPIC, kind, content, title=title)
        if title in {q.relevant_title for q in QUERIES}:
            relevant[title] = int(note["id"].removeprefix("note-"))
    return storage, relevant


def token_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def measure(db_path: str, repeats: int = 3) -> dict[str, Any]:
    storage, relevant = build_fixture(db_path)
    manager = SessionManager(storage)
    per_query: list[dict[str, Any]] = []
    for query in QUERIES:
        latencies: list[float] = []
        ranked: list[int] = []
        for _ in range(repeats):
            start = time.perf_counter_ns()
            results = manager.search_notes_fts(TOPIC, query.text, limit=10)
            latencies.append((time.perf_counter_ns() - start) / 1_000_000)
            ranked = [int(result["id"]) for result in results]
        expected = relevant[query.relevant_title]
        first = next((rank for rank, note_id in enumerate(ranked, 1) if note_id == expected), None)
        per_query.append({
            "id": query.identifier,
            "query": query.text,
            "relevant_id": expected,
            "ranked_ids": ranked,
            "first_relevant_rank": first,
            "recall": {str(k): int(expected in ranked[:k]) for k in (1, 5, 10)},
            "precision": {str(k): sum(1 for note_id in ranked[:k] if note_id == expected) / min(k, len(ranked) or k) for k in (1, 5, 10)},
            "irrelevant_results": sum(note_id != expected for note_id in ranked),
            "token_count": token_count(query.text) + sum(
                token_count(str(result.get("content", "")))
                for result in manager.search_notes_fts(TOPIC, query.text, limit=10)
            ),
            "latency_ms": latencies,
        })
    storage.close()

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    all_latencies = [value for item in per_query for value in item["latency_ms"]]
    metrics = {
        "queries": len(per_query),
        "repeats": repeats,
        "recall@1": mean([item["recall"]["1"] for item in per_query]),
        "recall@5": mean([item["recall"]["5"] for item in per_query]),
        "recall@10": mean([item["recall"]["10"] for item in per_query]),
        "mrr": mean([1 / item["first_relevant_rank"] if item["first_relevant_rank"] else 0 for item in per_query]),
        "precision": mean([item["precision"]["10"] for item in per_query]),
        "irrelevant_result_rate": mean([item["irrelevant_results"] / max(1, len(item["ranked_ids"])) for item in per_query]),
        "latency_ms": {"mean": mean(all_latencies), "p50": statistics.median(all_latencies), "max": max(all_latencies)},
        "token_count": {"mean_per_query": mean([item["token_count"] for item in per_query]), "total": sum(item["token_count"] for item in per_query)},
    }
    return {"dataset_sha256": dataset_digest(), "topic": TOPIC, "command": RUN_COMMAND, "environment": environment(), "metrics": metrics, "results": per_query}


def environment() -> dict[str, str]:
    return {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version, "cwd": os.getcwd()}


def markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    env = report["environment"]
    lines = [
        "# Memory retrieval benchmark baseline",
        "",
        f"Dataset SHA-256: `{report['dataset_sha256']}`",
        f"Command: `{report['command']}`",
        f"Queries: {metrics['queries']} (repeats: {metrics['repeats']})",
        "",
        "## Environment",
        f"- Python: `{env['python']}`",
        f"- SQLite: `{env['sqlite']}`",
        f"- Platform: `{env['platform']}`",
        f"- Working directory: `{env['cwd']}`",
        "",
        "## Baseline metrics",
        f"- Recall@1: `{metrics['recall@1']:.4f}`",
        f"- Recall@5: `{metrics['recall@5']:.4f}`",
        f"- Recall@10: `{metrics['recall@10']:.4f}`",
        f"- MRR: `{metrics['mrr']:.4f}`",
        f"- Precision@10: `{metrics['precision']:.4f}`",
        f"- Irrelevant-result rate: `{metrics['irrelevant_result_rate']:.4f}`",
        f"- Latency mean/p50/max ms: `{metrics['latency_ms']['mean']:.4f}` / `{metrics['latency_ms']['p50']:.4f}` / `{metrics['latency_ms']['max']:.4f}`",
        f"- Tokens mean/total: `{metrics['token_count']['mean_per_query']:.2f}` / `{metrics['token_count']['total']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark/baseline.json"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = measure(str(args.output.with_suffix(".db")), args.repeats)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(".md").write_text(markdown(report))
    args.output.with_suffix(".db").unlink()


if __name__ == "__main__":
    main()
