"""Tests for the memory retrieval benchmark."""

from __future__ import annotations

import json
import subprocess
import sys

from benchmarks.memory_benchmark import CATEGORIES, FAILURE_CLASSES, QUERIES, dataset_digest, measure


def test_dataset_has_at_least_110_unique_labeled_queries_and_required_categories():
    identifiers = [query.identifier for query in QUERIES]
    texts = [query.text for query in QUERIES]
    assert len(QUERIES) >= 110
    assert len(identifiers) == len(set(identifiers))
    assert len(texts) == len(set(texts))
    assert {query.category for query in QUERIES} >= set(CATEGORIES)
    assert {query.project for query in QUERIES} == {"atlas", "beacon", "cedar"}


def test_dataset_includes_no_answer_queries():
    assert sum(query.no_answer for query in QUERIES) >= 1
    assert all(not query.gold for query in QUERIES if query.no_answer)


def test_dataset_digest_is_deterministic():
    source = subprocess.run(
        [sys.executable, "-c", "from benchmarks.memory_benchmark import dataset_digest; print(dataset_digest())"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert source.stdout.strip() == dataset_digest()


def test_measure_reports_all_required_metrics(tmp_path):
    report = measure(str(tmp_path / "benchmark.db"), repeats=1)
    metrics = report["metrics"]
    assert metrics["queries"] == len(QUERIES) >= 110
    assert set(metrics["recall"]) == {"1", "3", "5", "10"}
    assert set(metrics["precision"]) == {"1", "3", "5", "10"}
    assert set(metrics) >= {
        "mrr",
        "ndcg",
        "irrelevant_rate",
        "no_answer_false_positive_rate",
        "latency_ms",
        "tokens",
        "superseded_retrieval_rate",
        "historical_accuracy",
        "contradiction_accuracy",
        "failure_classification_counts",
    }
    assert set(metrics["failure_classification_counts"]) == set(FAILURE_CLASSES)
    assert report["dataset"]["sha256"] == dataset_digest()
    assert report["dataset"]["version"]
    assert report["code_version"]
    assert report["timestamp_utc"]
    assert report["config"]["repeats"] == 1
    assert len(report["results"]) == len(QUERIES)
    assert all("gold_relevance" in result for result in report["results"])


def test_report_is_json_serializable(tmp_path):
    report = measure(str(tmp_path / "benchmark.db"), repeats=1)
    json.dumps(report)
