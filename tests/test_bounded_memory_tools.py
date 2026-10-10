"""Regression tests for the tool blowups that made BaseMem look hung.

Two independent problems:

* `resolve_contradictions` scanned every note pair in a topic and returned
  every match uncapped -- 10s and 686KB on a 1000-note topic -- while writing
  supersessions on each call.
* `_auto_link_note` reloaded and re-tokenized the whole topic on every insert,
  producing hundreds of thousands of weak auto edges.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from storage.db import StorageManager
from storage.sessions import SessionManager

ROOT = Path(__file__).resolve().parents[1]


def _manager(tmp_path, name="db.sqlite") -> SessionManager:
    return SessionManager(StorageManager(str(tmp_path / name)))


def test_resolve_contradictions_is_read_only_by_default(tmp_path):
    manager = _manager(tmp_path)
    manager.add_note("", "t", "DECISION", "We decided to use Redis for the session cache.")
    manager.add_note("", "t", "DECISION", "We decided to use PostgreSQL for the cache instead of Redis.")

    result = manager.resolve_contradictions("t")

    assert result["applied"] is False
    assert result["resolved_count"] == 1
    assert result["conflicts"][0]["reason"] == "explicitly_replaced"
    # the older note is still active: a review aid must not mutate by surprise
    assert len(manager.list_notes("t", include_superseded=True)) == 2
    assert manager.list_notes("t").__len__() == 2


def test_resolve_contradictions_applies_only_when_asked(tmp_path):
    manager = _manager(tmp_path)
    manager.add_note("", "t", "DECISION", "We decided to use Redis for the session cache.")
    manager.add_note("", "t", "DECISION", "We decided to use PostgreSQL for the cache instead of Redis.")

    result = manager.resolve_contradictions("t", apply=True)

    assert result["applied"] is True
    assert len(manager.list_notes("t")) == 1
    assert len(manager.list_notes("t", include_superseded=True)) == 2


def test_resolve_contradictions_ignores_unrelated_notes(tmp_path):
    manager = _manager(tmp_path)
    manager.add_note("", "t", "DECISION", "We decided to use Redis for the session cache.")
    manager.add_note("", "t", "FACT", "The office plants ferns near the north windows.")

    assert manager.resolve_contradictions("t")["resolved_count"] == 0


def test_resolve_contradictions_respects_limit_and_stays_small(tmp_path):
    manager = _manager(tmp_path)
    for i in range(40):
        manager.add_note("", "t", "DECISION", f"Decision {i}: we keep shared token alpha beta here.")

    result = manager.resolve_contradictions("t", limit=5)

    assert len(result["conflicts"]) <= 5
    assert len(json.dumps(result)) < 4000


def test_auto_link_is_sparse_not_one_edge_per_neighbour(tmp_path):
    manager = _manager(tmp_path)
    for i in range(25):
        manager.add_note("", "t", "FACT", f"shared token alpha beta gamma delta note {i}")

    edges = manager.storage.connection.execute(
        "SELECT COUNT(*) FROM note_links WHERE link_type = 'lexical_related'"
    ).fetchone()[0]

    # dense linking would produce ~300; the cap keeps it to 10 per note
    assert edges <= 25 * SessionManager.AUTO_LINK_MAX_PER_NOTE
    assert edges > 0


def test_contradiction_scan_tokenizes_each_note_once(tmp_path, monkeypatch):
    """The scan used to tokenize both sides of every pair: O(n^2) tokenizations.

    Tokenizing each note once up front is O(n) and yields the same candidates.
    """
    manager = _manager(tmp_path)
    for i in range(120):
        manager.add_note("", "big", "FACT", f"note {i} mentions shared vocabulary alpha beta gamma")

    calls = {"n": 0}
    real = SessionManager._tokenize

    def counting(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(SessionManager, "_tokenize", staticmethod(counting))
    result = manager.resolve_contradictions("big", limit=1)
    scanned = result["scanned"]

    assert calls["n"] <= scanned * 2, f"{calls['n']} tokenizations for {scanned} notes"
    # a quadratic implementation would need ~scanned^2 calls
    assert calls["n"] < scanned * scanned // 10


def test_contradiction_scan_finds_candidates_among_many(tmp_path):
    manager = _manager(tmp_path)
    for i in range(120):
        manager.add_note("", "big", "FACT", f"note {i} mentions shared vocabulary alpha beta gamma")
    manager.add_note("", "big", "DECISION", "We chose PostgreSQL for sessions instead of Redis.")
    manager.add_note("", "big", "DECISION", "We chose Redis for sessions.")

    result = manager.resolve_contradictions("big", limit=50)
    pairs = {(c["superseded_note_id"], c["active_note_id"]) for c in result["conflicts"]}

    # note-121 says "PostgreSQL ... instead of Redis", so Redis is superseded
    assert ("note-122", "note-121") in pairs


def test_entrypoint_help_exits_even_when_stdin_stays_open():
    """`mem-mcp.py --help` used to be discarded, leaving a stdio server blocking
    forever on an interactive terminal."""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "mem-mcp.py"), "--help"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("--help blocked with stdin open")

    assert proc.returncode == 0
    assert "usage: mem-mcp" in out


def test_entrypoint_rejects_unknown_flags():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "mem-mcp.py"), "--definitely-not-a-flag"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "unrecognized arguments" in proc.stderr
