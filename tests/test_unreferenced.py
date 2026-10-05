"""Unreferenced-symbol detection, and the false positives it must filter.

The first corpus run showed the raw `NOT (a)<-[:calls]-()` query is not usable
on its own: go reported 307 candidates of which 292 were test functions called
by a reflection-based runner, and 17 of 35 repos hit the query limit.
"""

import pytest

from indexer.deadcode import unreferenced
from indexer.entrypoints import is_entry_point, is_standalone_path, is_test_path
from indexer.indexer import CodeIndexer


@pytest.fixture
def idx(tmp_path):
    (tmp_path / "lib.py").write_text(
        "def called():\n    return 1\n\n\n"
        "def never_called():\n    return 2\n\n\n"
        "def main():\n    return called()\n"
    )
    (tmp_path / "lib_test.py").write_text(
        "def test_something():\n    return 1\n"
    )
    ix = CodeIndexer(str(tmp_path))
    ix.index_project(_max_workers=1)
    yield ix
    ix.close()


# ── path conventions ────────────────────────────────────────────────


@pytest.mark.parametrize("path", [
    "lib_test.go", "pkg/foo_test.py", "src/foo.test.js",
    "tests/bootstrap.php", "test/helper.rb", "/app/tests/x.rb",
    "spec/models/user_spec.rb", "src/__tests__/x.tsx", "FooTest.java",
])
def test_test_paths(path):
    assert is_test_path(path), path


@pytest.mark.parametrize("path", [
    "contests/entry.py", "src/latest.py", "attestation/main.go",
    "src/protest.py", "mytest/helper.rb",
])
def test_test_paths_do_not_over_match(path):
    assert not is_test_path(path), path


@pytest.mark.parametrize("path", [
    "samples/demo.lua", "examples/basic.rb", "testdata/fixture.json",
    "vendor/lib/x.go", "fixtures/y.py",
])
def test_standalone_paths(path):
    assert is_standalone_path(path), path


# ── entry points ────────────────────────────────────────────────────


@pytest.mark.parametrize("name,lang", [
    ("main", "go"), ("init", "go"), ("TestMain", "go"),
    ("__init__", "python"), ("setUp", "python"), ("__repr__", "python"),
    ("main", "java"), ("toString", "java"), ("equals", "java"),
    ("constructor", "javascript"), ("render", "javascript"),
    ("start_link", "erlang"), ("handle_call", "elixir"),
])
def test_entry_points(name, lang):
    assert is_entry_point(name, lang), f"{name}/{lang}"


@pytest.mark.parametrize("name,lang", [
    ("testing", "python"),      # prefix match must not swallow ordinary names
    ("specify", "ruby"),
    ("benchmarker", "python"),
    ("gt", "go"),               # genuinely dead in cobra, must not be filtered
    ("trimRightSpace", "go"),
])
def test_non_entry_points(name, lang):
    assert not is_entry_point(name, lang), f"{name}/{lang}"


# ── the report ──────────────────────────────────────────────────────


def test_never_called_is_reported(idx):
    r = unreferenced(idx, limit=100)
    kept = " ".join(r["sample"])
    assert "never_called" in kept, kept


def test_called_symbols_are_not_reported(idx):
    names = [s.split(" (")[0] for s in unreferenced(idx, limit=100)["sample"]]
    assert "called" not in names, names
    assert "main" not in names, names


def test_test_symbols_are_filtered(idx):
    r = unreferenced(idx, limit=100)
    assert r["skipped_test_paths"] >= 1
    assert "test_something" not in " ".join(r["sample"])


def test_entry_points_are_filtered_by_default(idx):
    r = unreferenced(idx, limit=100)
    assert "main" not in " ".join(r["sample"])


def test_entry_points_can_be_included(idx):
    r = unreferenced(idx, limit=100, include_entry_points=True)
    assert "main" in " ".join(r["sample"])


def test_capped_runs_report_low_confidence(idx):
    r = unreferenced(idx, limit=1)
    assert r["capped"] is True
    assert r["confidence"].startswith("LOW")


def test_uncapped_runs_report_caveat_not_a_verdict(idx):
    r = unreferenced(idx, limit=100)
    assert r["capped"] is False
    assert "MEDIUM" in r["confidence"]
    assert "confirm before deleting" in r["confidence"]


def test_every_result_carries_a_location(idx):
    r = unreferenced(idx, limit=100)
    assert all("(" in s and s.endswith(")") for s in r["sample"]), r["sample"]