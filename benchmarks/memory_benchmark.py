"""Deterministic labeled memory retrieval benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.db import StorageManager
from storage.sessions import SessionManager

DATASET_VERSION = "2026-09-25.1"
RUN_COMMAND = "uv run python -m benchmarks.memory_benchmark --output benchmark/<report>.json --repeats 3"
RETRIEVAL_LIMIT = 10
RELEVANCE_GRADES = ("irrelevant", "historical_only", "relevant", "superseded", "highly_relevant")
CATEGORIES = (
    "DIRECT_FACT",
    "DECISION",
    "WHY_QUESTION",
    "CONSTRAINT",
    "ARCHITECTURE",
    "BUG",
    "WORKAROUND",
    "DISCOVERY",
    "PREFERENCE",
    "CODE_RELATED",
    "HISTORICAL",
    "SUPERSESSION",
    "CONTRADICTION",
    "SCOPE",
    "AMBIGUOUS",
    "IRRELEVANT",
)
FAILURE_CLASSES = (
    "lexical",
    "scope",
    "temporal",
    "supersession",
    "type",
    "importance",
    "confidence",
    "graph",
    "ranking",
    "noise",
)

PROJECTS = (
    {
        "slug": "atlas",
        "name": "Atlas Ledger",
        "direct_fact": "Atlas Ledger stores settled transactions in an append-only local journal.",
        "decision": "The Atlas team chose SQLite WAL mode for transaction durability without a server.",
        "why": "Atlas uses SQLite because embedded durability keeps the ledger usable during network outages.",
        "constraint": "Atlas Ledger must preserve seven years of settled transaction history.",
        "architecture": "Atlas architecture separates journal ingestion, reconciliation, and export workers.",
        "bug": "The Atlas duplicate-reconciliation bug affected replay during clock skew.",
        "workaround": "For the Atlas clock-skew replay bug, disable workers and replay one shard at a time.",
        "discovery": "The Atlas audit found that reconciliation delayed alerts by twelve minutes.",
        "preference": "Atlas maintainers strongly prefer explicit SQL over an ORM for financial paths.",
        "code": "The Atlas settlement path is implemented in settlement/ledger_writer.py.",
        "historical": "Atlas originally used a polling export job before journal ingestion existed.",
        "superseded": "Atlas formerly used a cron export every fifteen minutes.",
        "contradiction": "Two Atlas design notes conflict on whether exports run continuously or hourly.",
        "scope": "Atlas reconciliation workers are excluded from the mobile client release.",
        "ambiguous": "The Atlas report named a performance issue but did not identify a subsystem.",
        "irrelevant": "Atlas uses teal launch banners only during internal demos.",
        "important": "Reconciling duplicate settlements is Atlas's highest-priority operational concern.",
        "low_confidence": "An Atlas engineer suspected ledger corruption without confirming the cause.",
        "graph": "Atlas journal events are graph-linked to reconciliation and export notes.",
        "noise": "The Atlas office plants ferns near the north windows.",
    },
    {
        "slug": "beacon",
        "name": "Beacon Router",
        "direct_fact": "Beacon Router records accepted routes in a local event stream.",
        "decision": "The Beacon team selected a binary routing protocol to minimize mobile payloads.",
        "why": "Beacon chose binary routing because field devices had narrow bandwidth.",
        "constraint": "Beacon Router route frames cannot exceed eight kilobytes.",
        "architecture": "Beacon architecture contains ingress adapters, policy evaluation, and egress workers.",
        "bug": "The Beacon route-flapping bug occurred when upstream keepalives expired.",
        "workaround": "For the Beacon route-flapping bug, pin the upstream peer before restarting ingress.",
        "discovery": "The Beacon load test discovered that policy evaluation dominated route latency.",
        "preference": "Beacon maintainers prefer boring protocols over experimental transport features.",
        "code": "Beacon policy evaluation lives in router/policy_evaluator.py.",
        "historical": "Beacon initially polled routing tables before receiving pushed events.",
        "superseded": "Beacon previously polled routing tables every thirty seconds.",
        "contradiction": "Beacon design notes contradict each other on whether push or poll is canonical.",
        "scope": "Beacon egress workers do not run in the embedded field gateway.",
        "ambiguous": "A Beacon incident report used 'latency' without naming ingress or egress.",
        "irrelevant": "Beacon's conference booth uses green plants beside brochures.",
        "important": "Preventing route flapping is Beacon's highest-priority production concern.",
        "low_confidence": "A Beacon operator suspected a hardware fault but gathered no packet evidence.",
        "graph": "Beacon ingress events are graph-linked to policy and egress notes.",
        "noise": "Beacon's demo balloons are inflated every morning.",
    },
    {
        "slug": "cedar",
        "name": "Cedar Scheduler",
        "direct_fact": "Cedar Scheduler publishes confirmed jobs to a durable work queue.",
        "decision": "The Cedar team adopted lease-based execution for cancellable background jobs.",
        "why": "Cedar uses leases because workers can disappear without blocking every queued job.",
        "constraint": "Cedar Scheduler job payloads cannot contain executable functions.",
        "architecture": "Cedar architecture separates intake, scheduling, lease management, and completion storage.",
        "bug": "The Cedar duplicate-execution bug followed worker clock adjustments.",
        "workaround": "For the Cedar duplicate-execution bug, let the current lease expire before restarting one worker.",
        "discovery": "The Cedar load test found that completion storage caused tail latency.",
        "preference": "Cedar maintainers prefer pull-based scheduling over centralized push dispatch.",
        "code": "Cedar lease management is implemented in scheduler/lease_manager.py.",
        "historical": "Cedar originally executed jobs immediately in the web request process.",
        "superseded": "Cedar previously executed jobs immediately inside the web request.",
        "contradiction": "Cedar notes conflict on whether the scheduler guarantees execution order.",
        "scope": "Cedar completion history is excluded from the lightweight mobile worker.",
        "ambiguous": "A Cedar alert mentioned slow 'jobs' without identifying intake or completion.",
        "irrelevant": "Cedar office mugs are printed with a cartoon owl.",
        "important": "Preventing duplicate execution is Cedar's highest-priority reliability concern.",
        "low_confidence": "A Cedar report guessed that storage contention caused retries.",
        "graph": "Cedar lease events are graph-linked to scheduling and completion notes.",
        "noise": "Cedar picnic tables are repainted after spring storms.",
    },
)


@dataclass(frozen=True)
class NoteSpec:
    label: str
    project: str
    category: str
    content: str
    importance: float = 0.5
    confidence: float = 0.9


@dataclass(frozen=True)
class Query:
    identifier: str
    project: str
    category: str
    text: str
    gold: dict[str, str]
    no_answer: bool = False


def make_notes() -> list[NoteSpec]:
    notes = [
        NoteSpec(
            label=f"{project['slug']}.{category.lower()}",
            project=project["slug"],
            category=category,
            content=project[CATEGORY_FIELDS[category]],
            importance=0.9 if category in {"SUPERSESSION", "CONTRADICTION", "PREFERENCE"} else 0.5,
        )
        for project in PROJECTS
        for category in CATEGORIES
    ]
    extras = (
        ("important", "PREFERENCE", "important", 0.95, 0.9),
        ("low_confidence", "DISCOVERY", "low_confidence", 0.5, 0.35),
        ("graph", "ARCHITECTURE", "graph", 0.7, 0.9),
        ("noise", "IRRELEVANT", "noise", 0.1, 0.9),
    )
    for project in PROJECTS:
        notes.extend(
            NoteSpec(f"{project['slug']}.{label}", project["slug"], category, project[field], importance, confidence)
            for label, category, field, importance, confidence in extras
        )
    return notes


CATEGORY_FIELDS = {
    "DIRECT_FACT": "direct_fact",
    "DECISION": "decision",
    "WHY_QUESTION": "why",
    "CONSTRAINT": "constraint",
    "ARCHITECTURE": "architecture",
    "BUG": "bug",
    "WORKAROUND": "workaround",
    "DISCOVERY": "discovery",
    "PREFERENCE": "preference",
    "CODE_RELATED": "code",
    "HISTORICAL": "historical",
    "SUPERSESSION": "superseded",
    "CONTRADICTION": "contradiction",
    "SCOPE": "scope",
    "AMBIGUOUS": "ambiguous",
    "IRRELEVANT": "irrelevant",
}
NOTES = make_notes()
NOTE_LABELS = {note.label for note in NOTES}
BASE_CATEGORIES = list(CATEGORIES)
CATEGORY_QUESTIONS = {
    "DIRECT_FACT": ("What is stored in the {name} journal?", "relevant"),
    "DECISION": ("Which technology did the {name} team choose?", "highly_relevant"),
    "WHY_QUESTION": ("Why did the {name} team make its durable storage choice?", "relevant"),
    "CONSTRAINT": ("What hard requirement governs {name} payloads and retention?", "relevant"),
    "ARCHITECTURE": ("Which components define the {name} architecture?", "highly_relevant"),
    "BUG": ("Which failure affected the {name} production system?", "relevant"),
    "WORKAROUND": ("What is the documented workaround for the {name} failure?", "highly_relevant"),
    "DISCOVERY": ("What did the {name} load test actually discover?", "relevant"),
    "PREFERENCE": ("What implementation preference does the {name} team follow?", "relevant"),
    "CODE_RELATED": ("Which file implements the central {name} processing path?", "relevant"),
    "HISTORICAL": ("What did {name} do before the current architecture?", "historical_only"),
    "SUPERSESSION": ("What superseded {name} policy should be recognized as old?", "relevant"),
    "CONTRADICTION": ("Which {name} design records disagree with each other?", "relevant"),
    "SCOPE": ("Which component is excluded from the {name} constrained release?", "relevant"),
    "AMBIGUOUS": ("What ambiguous {name} symptom is documented?", "historical_only"),
    "IRRELEVANT": ("Which unrelated {name} office detail is recorded?", "relevant"),
}


def make_queries() -> list[Query]:
    queries: list[Query] = []
    for project in PROJECTS:
        slug = project["slug"]
        name = project["name"]
        for pass_number in (1, 2):
            for category in BASE_CATEGORIES:
                question, grade = CATEGORY_QUESTIONS[category]
                label = f"{slug}.{category.lower()}"
                gold = {label: grade}

                if category == "HISTORICAL":
                    gold[f"{slug}.direct_fact"] = "irrelevant"
                if category == "SUPERSESSION":
                    gold[f"{slug}.superseded"] = "relevant"
                    gold[f"{slug}.decision"] = "highly_relevant"
                if category == "CONTRADICTION":
                    gold[f"{slug}.decision"] = "relevant"
                    gold[f"{slug}.architecture"] = "relevant"
                prefix = "Please answer: " if pass_number == 2 else ""
                queries.append(Query(f"{slug}.q{len(queries) + 1:03d}", slug, category, prefix + question.format(name=name), gold))
        extras = (
            ("PREFERENCE", "What concern is most important for {name} operators?", "important", "highly_relevant"),
            ("DISCOVERY", "Which causal diagnosis for {name} is explicitly unconfirmed?", "low_confidence", "historical_only"),
            ("ARCHITECTURE", "How are related {name} events represented across the graph?", "graph", "highly_relevant"),
            ("IRRELEVANT", "Which unrelated {name} object is mentioned in the notes?", "irrelevant", "relevant"),
        )
        for category, question, note_key, grade in extras:
            label = f"{slug}.{note_key}"
            queries.append(
                Query(f"{slug}.q{len(queries) + 1:03d}", slug, category, question.format(name=name), {label: grade})
            )
        for variant in range(4):
            queries.append(
                Query(
                    f"{slug}.q{len(queries) + 1:03d}",
                    slug,
                    "IRRELEVANT" if variant % 2 else "AMBIGUOUS",
                    f"What lunar rover charging standard was approved for {name} in cycle {variant + 7}?",
                    {},
                    True,
                )
            )
    return queries


QUERIES = make_queries()


def dataset_digest() -> str:
    payload = json.dumps(
        {"dataset_version": DATASET_VERSION, "notes": [asdict(note) for note in NOTES], "queries": [asdict(query) for query in QUERIES]},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def token_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def percentile(values: list[float | int], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))


def code_version() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_fixture(db_path: str) -> tuple[StorageManager, SessionManager, dict[str, int]]:
    storage = StorageManager(db_path)
    manager = SessionManager(storage)
    ids: dict[str, int] = {}
    for note in NOTES:
        project = next(project for project in PROJECTS if project["slug"] == note.project)
        stored = manager.add_note(
            "",
            project["name"],
            note.category,
            note.content,
            title=note.label,
            observed_at="2026-01-01T00:00:00+00:00",
            importance=note.importance,
            confidence=note.confidence,
            scope=project["name"],
            source="synthetic-benchmark",
        )
        stored_id = str(stored["id"])
        ids[note.label] = int(stored_id.removeprefix("note-"))
    return storage, manager, ids


def failure_classification(query: Query, ranked_labels: list[str], grades: dict[str, str]) -> list[str]:
    positives = {label for label, grade in grades.items() if grade != "irrelevant"}
    false_positive = bool(positives.intersection(ranked_labels))
    if query.no_answer and false_positive:
        return ["noise"]
    if not positives:
        return []
    failures: list[str] = []
    missing = positives.difference(ranked_labels)
    if missing:
        failures.append("lexical")
    best_grade = max(grades.values(), key=lambda grade: RELEVANCE_GRADES.index(grade))
    if ranked_labels and grades.get(ranked_labels[0], "irrelevant") != best_grade:
        failures.append("ranking")
    category_failures = {
        "DIRECT_FACT": "type",
        "DECISION": "type",
        "WHY_QUESTION": "lexical",
        "CONSTRAINT": "scope",
        "ARCHITECTURE": "graph",
        "BUG": "type",
        "WORKAROUND": "ranking",
        "DISCOVERY": "confidence",
        "PREFERENCE": "importance",
        "CODE_RELATED": "type",
        "HISTORICAL": "temporal",
        "SUPERSESSION": "supersession",
        "CONTRADICTION": "temporal",
        "SCOPE": "scope",
        "AMBIGUOUS": "noise",
        "IRRELEVANT": "noise",
    }
    category_failure = category_failures[query.category]
    if missing or category_failure in {"scope", "temporal", "supersession", "confidence", "graph", "importance"}:
        failures.append(category_failure)
    return sorted(set(failures))


def measure(db_path: str, repeats: int = 3) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    storage, manager, note_ids = build_fixture(db_path)
    per_query: list[dict[str, Any]] = []
    try:
        for query in QUERIES:
            latencies: list[float] = []
            ranked: list[dict[str, Any]] = []
            project = next(project for project in PROJECTS if project["slug"] == query.project)
            for _ in range(repeats):
                start = time.perf_counter_ns()
                ranked = manager.rank_memories(project["name"], query.text, limit=RETRIEVAL_LIMIT, historical=query.category == "HISTORICAL")
                latencies.append((time.perf_counter_ns() - start) / 1_000_000)
            id_to_label = {note_id: label for label, note_id in note_ids.items()}
            ranked_ids = [int(result["id"]) for result in ranked]
            ranked_labels = [id_to_label[note_id] for note_id in ranked_ids]
            complete_grades = {note.label: query.gold.get(note.label, "irrelevant") for note in NOTES if note.project == query.project}
            positives = [label for label, grade in complete_grades.items() if grade != "irrelevant"]
            gains = [RELEVANCE_GRADES.index(complete_grades.get(label, "irrelevant")) for label in ranked_labels]
            ideal = sorted((RELEVANCE_GRADES.index(grade) for grade in complete_grades.values()), reverse=True)[:RETRIEVAL_LIMIT]
            first_relevant = next((rank for rank, label in enumerate(ranked_labels, 1) if complete_grades.get(label) != "irrelevant"), None)
            token_total = token_count(query.text) + sum(token_count(str(result.get("content", ""))) for result in ranked)
            per_query.append(
                {
                    "id": query.identifier,
                    "project": query.project,
                    "category": query.category,
                    "query": query.text,
                    "no_answer": query.no_answer,
                    "gold_relevance": complete_grades,
                    "ranked_ids": ranked_ids,
                    "ranked_labels": ranked_labels,
                    "first_relevant_rank": first_relevant,
                    "recall": {str(k): sum(label in positives for label in ranked_labels[:k]) / len(positives) if positives else None for k in (1, 3, 5, 10)},
                    "precision": {str(k): sum(complete_grades.get(label) != "irrelevant" for label in ranked_labels[:k]) / k for k in (1, 3, 5, 10)},
                    "dcg": dcg(gains),
                    "ndcg": dcg(gains) / dcg(ideal) if dcg(ideal) else 1.0,
                    "irrelevant_retrieved": sum(gains) == 0,
                    "false_positive": bool(set(positives).intersection(ranked_labels)),
                    "tokens": token_total,
                    "latency_ms": latencies,
                    "failure_classification": failure_classification(query, ranked_labels, complete_grades),
                }
            )
    finally:
        storage.close()

    answerable = [item for item in per_query if not item["no_answer"]]
    no_answer = [item for item in per_query if item["no_answer"]]
    all_latencies = [value for item in per_query for value in item["latency_ms"]]
    all_tokens = [item["tokens"] for item in per_query]
    superseded = [item for item in per_query if item["category"] == "SUPERSESSION"]
    historical = [item for item in per_query if item["category"] == "HISTORICAL"]
    contradictions = [item for item in per_query if item["category"] == "CONTRADICTION"]

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    metrics = {
        "queries": len(per_query),
        "answerable_queries": len(answerable),
        "no_answer_queries": len(no_answer),
        "repeats": repeats,
        "recall": {str(k): mean([item["recall"][str(k)] for item in answerable]) for k in (1, 3, 5, 10)},
        "precision": {str(k): mean([item["precision"][str(k)] for item in per_query]) for k in (1, 3, 5, 10)},
        "mrr": mean([1 / item["first_relevant_rank"] if item["first_relevant_rank"] else 0 for item in answerable]),
        "ndcg": mean([item["ndcg"] for item in answerable]),
        "irrelevant_rate": sum(item["irrelevant_retrieved"] for item in per_query) / max(1, sum(len(item["ranked_labels"]) for item in per_query)),
        "no_answer_false_positive_rate": mean([int(item["false_positive"]) for item in no_answer]),
        "latency_ms": {"mean": mean(all_latencies), "p95": percentile(all_latencies, 0.95)},
        "tokens": {"mean": mean(all_tokens), "p95": percentile(all_tokens, 0.95), "total": sum(all_tokens)},
        "superseded_retrieval_rate": mean([int(f"{query.project}.superseded" in item["ranked_labels"]) for item in superseded]),
        "historical_accuracy": mean([int(f"{item['project']}.historical" in item["ranked_labels"]) for item in historical]),
        "contradiction_accuracy": mean([int(f"{item['project']}.contradiction" in item["ranked_labels"]) for item in contradictions]),
        "failure_classification_counts": {
            failure: sum(failure in item["failure_classification"] for item in per_query) for failure in FAILURE_CLASSES
        },
    }
    dataset = {
        "version": DATASET_VERSION,
        "sha256": dataset_digest(),
        "projects": [project["slug"] for project in PROJECTS],
        "categories": list(CATEGORIES),
    }
    config = {
        "retrieval_method": "SessionManager.rank_memories",
        "limit": RETRIEVAL_LIMIT,
        "repeats": repeats,
        "tokenizer": "regex_words",
        "gold_grades": list(RELEVANCE_GRADES),
    }
    return {
        "dataset": dataset,
        "code_version": code_version(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": RUN_COMMAND,
        "config": config,
        "environment": environment(),
        "metrics": metrics,
        "results": per_query,
    }


def environment() -> dict[str, str]:
    return {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version, "cwd": os.getcwd()}


def markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    env = report["environment"]
    lines = [
        "# Memory retrieval benchmark baseline",
        "",
        f"Dataset version: `{report['dataset']['version']}`",
        f"Dataset SHA-256: `{report['dataset']['sha256']}`",
        f"Code version: `{report['code_version']}`",
        f"Timestamp UTC: `{report['timestamp_utc']}`",
        f"Command: `{report['command']}`",
        (
            f"Queries: {metrics['queries']} (answerable: {metrics['answerable_queries']}, "
            f"no-answer: {metrics['no_answer_queries']}, repeats: {metrics['repeats']})"
        ),
        "",
        "## Environment",
        f"- Python: `{env['python']}`",
        f"- SQLite: `{env['sqlite']}`",
        f"- Platform: `{env['platform']}`",
        f"- Working directory: `{env['cwd']}`",
        "",
        "## Baseline metrics",
        (
            f"- Recall@1/3/5/10: `{metrics['recall']['1']:.4f}` / `{metrics['recall']['3']:.4f}` / "
            f"`{metrics['recall']['5']:.4f}` / `{metrics['recall']['10']:.4f}`"
        ),
        (
            f"- Precision@1/3/5/10: `{metrics['precision']['1']:.4f}` / `{metrics['precision']['3']:.4f}` / "
            f"`{metrics['precision']['5']:.4f}` / `{metrics['precision']['10']:.4f}`"
        ),
        f"- MRR: `{metrics['mrr']:.4f}`",
        f"- nDCG@10: `{metrics['ndcg']:.4f}`",
        f"- Irrelevant rate: `{metrics['irrelevant_rate']:.4f}`",
        f"- No-answer false positive rate: `{metrics['no_answer_false_positive_rate']:.4f}`",
        f"- Latency mean/p95 ms: `{metrics['latency_ms']['mean']:.4f}` / `{metrics['latency_ms']['p95']:.4f}`",
        f"- Tokens mean/p95/total: `{metrics['tokens']['mean']:.2f}` / `{metrics['tokens']['p95']:.0f}` / `{metrics['tokens']['total']}`",
        f"- Superseded retrieval rate: `{metrics['superseded_retrieval_rate']:.4f}`",
        f"- Historical accuracy: `{metrics['historical_accuracy']:.4f}`",
        f"- Contradiction accuracy: `{metrics['contradiction_accuracy']:.4f}`",
        "",
        "## Failure classification counts",
    ]
    lines.extend(f"- {failure}: `{count}`" for failure, count in metrics["failure_classification_counts"].items())
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark/baseline.json"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = measure(str(args.output.with_suffix(".db")), args.repeats)
    report["command"] = f"uv run python -m benchmarks.memory_benchmark --output {args.output} --repeats {args.repeats}"
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(".md").write_text(markdown(report))
    args.output.with_suffix(".db").unlink()


if __name__ == "__main__":
    main()
