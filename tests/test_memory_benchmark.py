"""Tests for the memory retrieval benchmark."""

from __future__ import annotations

import json

from benchmarks.memory_benchmark import NOTES, QUERIES, dataset_digest, measure


def test_dataset_has_unique_labeled_queries_and_relevant_notes():
    titles = [title for _, _, title in NOTES]
    relevant_titles = {query.relevant_title for query in QUERIES}
    assert len(titles) == len(set(titles))
    assert len(QUERIES) == 7
    assert relevant_titles <= set(titles)


def test_measure_reports_all_required_metrics(tmp_path):
    db_path = tmp_path / "benchmark.db"
    report = measure(str(db_path), repeats=1)
    metrics = report["metrics"]
    assert metrics["queries"] == 7
    assert set(metrics) >= {"recall@1", "recall@5", "recall@10", "mrr", "precision", "irrelevant_result_rate", "latency_ms", "token_count"}
    assert report["dataset_sha256"] == dataset_digest()
    assert len(report["results"]) == 7


def test_report_is_json_serializable(tmp_path):
    report = measure(str(tmp_path / "benchmark.db"), repeats=1)
    json.dumps(report)
