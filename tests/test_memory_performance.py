"""Focused tests for the reproducible performance benchmark."""

from __future__ import annotations

import json
import subprocess
import sys

from benchmarks.memory_performance import (
    ALL_SCALES,
    DEFAULT_SCALES,
    complexity_checks,
    deterministic_memories,
    run_profile,
)


def test_generation_is_deterministic_and_scales_are_opt_in():
    assert 100_000 not in DEFAULT_SCALES
    assert ALL_SCALES == (1_000, 10_000, 100_000)
    assert deterministic_memories(3) == deterministic_memories(3)
    assert len({memory.id for memory in deterministic_memories(1_000)}) == 1_000


def test_profile_reports_every_measurement(tmp_path):
    report = run_profile(1_000, output=tmp_path / "measurements.json")
    assert report["count"] == 1_000
    assert set(report) >= {
        "insert", "fts_search", "metadata_filter", "graph_traversal", "retrieval",
        "context_compilation", "database_size_bytes", "startup",
    }
    artifact = json.loads((tmp_path / "measurements.json").read_text())
    assert artifact["count"] == 1_000


def test_complexity_checks_identify_obvious_quadratic_growth():
    checks = complexity_checks([
        {"count": 1_000, "fts_search": {"ms": 1.0}},
        {"count": 10_000, "fts_search": {"ms": 20.0}},
    ])
    assert checks[0]["quadratic_suspected"] is False


def test_cli_help_exposes_explicit_100k_command():
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.memory_performance", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--include-100k" in result.stdout
