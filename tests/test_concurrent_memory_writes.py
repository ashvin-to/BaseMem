"""Empirical tests for concurrent multi-agent writes.

These assert invariants, not implementation details, so they fail on the
current code and pass once writes are made atomic.

Background: exec_stmt() commits after every single statement, so any
read-modify-write spanning two statements has a window where another agent
can change the row underneath it.
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3

from storage.db import StorageManager
from storage.sessions import SessionManager

FROZEN = "2026-01-01 00:00:00"


def _manager(path: str) -> SessionManager:
    return SessionManager(StorageManager(path))


def test_identical_note_is_not_duplicated(tmp_path, monkeypatch):
    manager = _manager(str(tmp_path / "dedup.db"))
    monkeypatch.setattr(SessionManager, "_now", staticmethod(lambda: FROZEN))

    manager.add_note("", "t", "DECISION", "We chose SQLite for durability.")
    manager.add_note("", "t", "DECISION", "We chose SQLite for durability.")

    rows = manager.storage.connection.execute(
        "SELECT COUNT(*) FROM notes WHERE topic = 't' AND content = ?",
        ("We chose SQLite for durability.",),
    ).fetchone()[0]

    assert rows == 1, f"expected 1 row, found {rows}"


def test_no_orphan_rows_from_a_repeated_note(tmp_path, monkeypatch):
    """A repeat must not leave a row nobody was ever told about.

    The lookup runs after an unconditional INSERT and there is no DELETE, so
    the second call creates a row it never returns. Asserting only that the
    returned id resolves is too weak: it does, while the extra row sits there.
    """
    manager = _manager(str(tmp_path / "which.db"))
    monkeypatch.setattr(SessionManager, "_now", staticmethod(lambda: FROZEN))

    first = manager.add_note("", "t", "DECISION", "Chose WAL mode.")
    second = manager.add_note("", "t", "DECISION", "Chose WAL mode.")

    rows = manager.storage.connection.execute(
        "SELECT id FROM notes WHERE topic = 't' AND content = ?", ("Chose WAL mode.",)
    ).fetchall()
    row_ids = {r["id"] for r in rows}
    returned_ids = {int(first["id"].split("-")[1]), int(second["id"].split("-")[1])}

    assert row_ids == returned_ids, (
        f"{len(row_ids)} row(s) on disk but only {len(returned_ids)} distinct id(s) "
        f"handed back; {sorted(row_ids - returned_ids)} were never returned to anyone"
    )


def _add_file_worker(db_path: str, tag: str, rounds: int) -> None:
    manager = _manager(db_path)
    try:
        for i in range(rounds):
            manager.update_planet("", "shared", file_path=tag + "-" + str(i) + ".py")
    finally:
        manager.storage.close()


def test_concurrent_file_updates_do_not_lose_writes(tmp_path):
    db_path = str(tmp_path / "files.db")
    _manager(db_path).update_planet("", "shared", current_state="seed")

    rounds = 60
    tags = ("alpha", "beta", "gamma", "delta")
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(target=_add_file_worker, args=(db_path, tag, rounds))
        for tag in tags
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=300)
        assert p.exitcode == 0, f"worker crashed with exitcode {p.exitcode}"

    import json as _json

    row = sqlite3.connect(db_path).execute(
        "SELECT files FROM planets WHERE topic = 'shared'"
    ).fetchone()
    stored = set(_json.loads(row[0] or "[]"))

    expected = {tag + "-" + str(i) + ".py" for tag in tags for i in range(rounds)}
    assert stored, "workers wrote nothing at all; the test proved nothing"
    missing = expected - stored
    assert not missing, (
        f"lost {len(missing)} of {len(expected)} concurrent writes "
        f"({len(stored)} survived): {sorted(missing)[:5]}"
    )


def _same_note_worker(db_path: str, rounds: int) -> None:
    manager = _manager(db_path)
    # Freeze the clock so every worker targets the *same* dedup key
    # (topic, created_at, content). Without this the writes land in different
    # seconds and are legitimately distinct rows -- that is a dedup-policy
    # question, not a lost-update race.
    manager._now = lambda: FROZEN
    try:
        for _ in range(rounds):
            manager.add_note("", "shared", "DECISION", "We decided to standardise on SQLite.")
    finally:
        manager.storage.close()


def test_concurrent_identical_notes_collapse_to_one(tmp_path):
    """Concurrent writes sharing one dedup key must produce exactly one row.

    Before the fix this was insert-then-look-up with no transaction, so all 30
    writers inserted and 30 rows survived.
    """
    db_path = str(tmp_path / "same.db")
    _manager(db_path).update_planet("", "shared", current_state="seed")

    rounds = 10
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_same_note_worker, args=(db_path, rounds)) for _ in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0, f"worker crashed with exitcode {p.exitcode}"

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE topic = 'shared' AND content = ?",
        ("We decided to standardise on SQLite.",),
    ).fetchone()[0]
    conn.close()

    assert rows == 1, f"expected 1 note from {rounds * 3} identical writes, found {rows}"


def test_same_content_in_different_seconds_is_not_deduped(tmp_path):
    """Documents the current dedup key rather than pretending it is broader.

    The key is (topic, created_at, content) and created_at has second
    granularity, so identical text logged a second apart yields two rows.
    Changing that is a product decision about whether re-logging a decision
    should refresh or duplicate it; it is not a concurrency fix.
    """
    manager = _manager(str(tmp_path / "window.db"))
    clock = {"now": "2026-01-01 00:00:00"}
    manager._now = lambda: clock["now"]

    manager.add_note("", "t", "DECISION", "Chose SQLite.")
    clock["now"] = "2026-01-01 00:00:01"
    manager.add_note("", "t", "DECISION", "Chose SQLite.")

    rows = manager.storage.connection.execute(
        "SELECT COUNT(*) FROM notes WHERE topic = 't'"
    ).fetchone()[0]
    assert rows == 2, "documented behaviour changed: dedup now spans time"
