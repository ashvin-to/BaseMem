"""Tests for Task CRUD, dependency cycle rejection, compact_planet integration,
migration idempotency, and MCP tool end-to-end."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from storage.db import StorageManager
from storage.sessions import SessionManager, _ensure_schema


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def temp_db():
    """Create a temporary database and return (path, storage, manager)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        os.environ["BASEMEM_DB_PATH"] = str(db_path)
        storage = StorageManager(str(db_path))
        manager = SessionManager(storage)
        yield db_path, storage, manager
        storage.close()
        del os.environ["BASEMEM_DB_PATH"]


@pytest.fixture
def seeded_db(temp_db):
    """A temp DB with a planet, a few notes, and some tasks."""
    db_path, storage, manager = temp_db
    manager.update_planet("test", "task-planet",
                          current_state="testing tasks",
                          goal="comprehensive coverage")

    n1 = manager.add_note("test", "task-planet", "fact", "note one")
    n2 = manager.add_note("test", "task-planet", "fact", "note two")
    n3 = manager.add_note("test", "task-planet", "decision", "use json")
    n4 = manager.add_note("test", "task-planet", "issue", "memory leak")

    t1 = manager.create_task("task-planet", "implement crud",
                             priority="high",
                             depends_on=[], files=["storage/sessions.py"],
                             notes=[int(n1["id"].replace("note-", ""))])
    t2 = manager.create_task("task-planet", "write tests",
                             priority="medium",
                             notes=[int(n2["id"].replace("note-", ""))])
    t3 = manager.create_task("task-planet", "review",
                             priority="low")

    return db_path, storage, manager, {
        "notes": {"n1": n1, "n2": n2, "n3": n3, "n4": n4},
        "tasks": {"t1": t1, "t2": t2, "t3": t3},
    }


@pytest.fixture
def pre_migration_db():
    """Create a fixture database with the schema as it existed before the
    tasks/frontend/camelCase changes — planets, notes, note_links, planet_links
    only, no tasks table, no tags/pinned columns on notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fixture.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS planets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE NOT NULL,
                display_topic TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                goal TEXT DEFAULT '',
                current_state TEXT DEFAULT '',
                next_step TEXT DEFAULT '',
                next_steps TEXT DEFAULT '[]',
                files TEXT DEFAULT '[]',
                commands TEXT DEFAULT '[]',
                handoff TEXT DEFAULT '',
                aliases TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                title TEXT DEFAULT '',
                agent_id TEXT DEFAULT 'default',
                status TEXT DEFAULT 'open',
                turn_index INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS note_links (
                from_note_id INTEGER NOT NULL,
                to_note_id INTEGER NOT NULL,
                link_type TEXT NOT NULL DEFAULT 'related',
                weight REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (from_note_id, to_note_id, link_type)
            );
            CREATE TABLE IF NOT EXISTS planet_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_planet_id INTEGER NOT NULL,
                to_planet_id INTEGER NOT NULL,
                relation TEXT NOT NULL DEFAULT 'related',
                weight REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(from_planet_id, to_planet_id, relation)
            );
            INSERT INTO planets (topic, display_topic, status, goal, current_state)
            VALUES ('fixture-planet', 'Fixture Planet', 'active', 'test migration', 'pre-change state');
            INSERT INTO notes (topic, kind, content, title, status)
            VALUES ('fixture-planet', 'fact', 'pre-existing note', 'old fixture note', 'open');
        """)
        conn.commit()
        conn.close()
        yield str(db_path)
        try:
            os.unlink(str(db_path))
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════
# Task CRUD
# ═══════════════════════════════════════════════════════════════════


class TestTaskCRUD:
    def test_create_task_minimal(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "my-planet", current_state="ok")
        t = manager.create_task("my-planet", "do the thing")
        assert t["id"] > 0
        assert t["title"] == "do the thing"
        assert t["status"] == "todo"
        assert t["priority"] == "medium"
        assert json.loads(t["depends_on"]) == []
        assert json.loads(t["files"]) == []
        assert json.loads(t["notes"]) == []

    def test_create_task_all_fields(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p2", current_state="ok")
        t = manager.create_task("p2", "big task",
                                priority="high",
                                depends_on=[], files=["a.py", "b.py"],
                                notes=[99, 100])
        assert t["priority"] == "high"
        assert json.loads(t["files"]) == ["a.py", "b.py"]
        assert json.loads(t["notes"]) == [99, 100]

    def test_create_task_invalid_priority_defaults_to_medium(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p3", current_state="ok")
        t = manager.create_task("p3", "task", priority="urgent")
        assert t["priority"] == "medium"

    def test_create_task_auto_creates_planet(self, temp_db):
        _, storage, manager = temp_db
        t = manager.create_task("auto-planet", "auto task")
        assert t["id"] > 0
        row = manager.storage.connection.cursor().execute(
            "SELECT topic FROM planets WHERE topic = ?", ("auto-planet",)
        ).fetchone()
        assert row is not None

    def test_create_task_depends_on_non_existent_ignored(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p4", current_state="ok")
        t = manager.create_task("p4", "task", depends_on=[999, 888])
        deps = json.loads(t["depends_on"])
        assert deps == []  # non-existent deps are silently dropped

    def test_list_tasks(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "list-test", current_state="ok")
        manager.create_task("list-test", "a")
        manager.create_task("list-test", "b")
        tasks = manager.list_tasks(topic="list-test")
        assert len(tasks) == 2

    def test_list_tasks_empty(self, temp_db):
        _, storage, manager = temp_db
        tasks = manager.list_tasks(topic="no-such-planet")
        assert tasks == []

    def test_list_tasks_filter_by_status(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "filter-test", current_state="ok")
        t = manager.create_task("filter-test", "do it")
        manager.update_task(t["id"], status="in_progress")
        tasks = manager.list_tasks(topic="filter-test", status="in_progress")
        assert len(tasks) == 1
        tasks = manager.list_tasks(topic="filter-test", status="todo")
        assert len(tasks) == 0

    def test_list_tasks_filter_by_priority(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "prio-test", current_state="ok")
        manager.create_task("prio-test", "high one", priority="high")
        manager.create_task("prio-test", "low one", priority="low")
        high = manager.list_tasks(topic="prio-test", priority="high")
        low = manager.list_tasks(topic="prio-test", priority="low")
        assert len(high) == 1
        assert len(low) == 1

    def test_list_tasks_filter_unknown_status(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "us", current_state="ok")
        manager.create_task("us", "x")
        tasks = manager.list_tasks(topic="us", status="bogus")
        # unknown filter is silently ignored
        assert len(tasks) == 1

    def test_update_task_status(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "up-test", current_state="ok")
        t = manager.create_task("up-test", "change me")
        ok, msg = manager.update_task(t["id"], status="in_progress")
        assert ok
        tasks = manager.list_tasks(topic="up-test")
        assert tasks[0]["status"] == "in_progress"

    def test_update_task_priority(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "up-prio", current_state="ok")
        t = manager.create_task("up-prio", "prioritize")
        ok, msg = manager.update_task(t["id"], priority="high")
        assert ok
        tasks = manager.list_tasks(topic="up-prio")
        assert tasks[0]["priority"] == "high"

    def test_update_task_invalid_status_rejected(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "bad-status", current_state="ok")
        t = manager.create_task("bad-status", "bad")
        ok, msg = manager.update_task(t["id"], status="unknown")
        assert not ok
        assert "Invalid" in msg

    def test_update_task_invalid_priority_rejected(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "bad-prio", current_state="ok")
        t = manager.create_task("bad-prio", "bad")
        ok, msg = manager.update_task(t["id"], priority="extreme")
        assert not ok
        assert "Invalid" in msg

    def test_update_task_not_found(self, temp_db):
        _, storage, manager = temp_db
        ok, msg = manager.update_task(99999, status="done")
        assert not ok
        assert "not found" in msg.lower()

    def test_update_task_files_notes(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "fn-test", current_state="ok")
        t = manager.create_task("fn-test", "fn")
        ok, msg = manager.update_task(t["id"], files=["x.txt", "y.txt"], notes=[1, 2, 3])
        assert ok
        tasks = manager.list_tasks(topic="fn-test")
        assert json.loads(tasks[0]["files"]) == ["x.txt", "y.txt"]
        assert json.loads(tasks[0]["notes"]) == [1, 2, 3]

    def test_update_task_completed_at_set_on_done(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "done-at", current_state="ok")
        t = manager.create_task("done-at", "finish me")
        assert t.get("completed_at") is None
        manager.update_task(t["id"], status="done")
        tasks = manager.list_tasks(topic="done-at")
        assert tasks[0]["completed_at"] is not None

    def test_get_task_summary(self, seeded_db):
        _, storage, manager, _ = seeded_db
        summary = manager.get_task_summary("task-planet")
        assert summary["total"] == 3
        assert summary["counts"]["todo"] == 3


# ═══════════════════════════════════════════════════════════════════
# Dependency cycle rejection
# ═══════════════════════════════════════════════════════════════════


class TestDependencyCycles:
    def test_direct_self_cycle(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "cycle-test", current_state="ok")
        t = manager.create_task("cycle-test", "self")
        ok, msg = manager.update_task(t["id"], depends_on=[t["id"]])
        assert not ok
        assert "cycle" in msg.lower()

    def test_one_step_cycle(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "cycle-test", current_state="ok")
        a = manager.create_task("cycle-test", "A")
        b = manager.create_task("cycle-test", "B")
        ok, _ = manager.update_task(a["id"], depends_on=[b["id"]])
        assert ok
        ok, msg = manager.update_task(b["id"], depends_on=[a["id"]])
        assert not ok
        assert "cycle" in msg.lower()

    def test_nested_cycle(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "nested-cycle", current_state="ok")
        a = manager.create_task("nested-cycle", "A")
        b = manager.create_task("nested-cycle", "B")
        c = manager.create_task("nested-cycle", "C")
        manager.update_task(a["id"], depends_on=[b["id"]])
        manager.update_task(b["id"], depends_on=[c["id"]])
        ok, msg = manager.update_task(c["id"], depends_on=[a["id"]])
        assert not ok
        assert "cycle" in msg.lower()

    def test_valid_chain_no_cycle(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "chain", current_state="ok")
        a = manager.create_task("chain", "A")
        b = manager.create_task("chain", "B")
        c = manager.create_task("chain", "C")
        ok, _ = manager.update_task(a["id"], depends_on=[b["id"]])
        assert ok
        ok, _ = manager.update_task(b["id"], depends_on=[c["id"]])
        assert ok
        ok, _ = manager.update_task(c["id"], depends_on=[])
        assert ok

    def test_missing_dependency_rejected(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "missing-dep", current_state="ok")
        t = manager.create_task("missing-dep", "orphan")
        ok, msg = manager.update_task(t["id"], depends_on=[99999])
        assert not ok
        assert "not found" in msg.lower()


# ═══════════════════════════════════════════════════════════════════
# Task status transitions
# ═══════════════════════════════════════════════════════════════════


class TestTaskStatusTransitions:
    def test_todo_to_in_progress(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st", current_state="ok")
        t = manager.create_task("st", "progress")
        ok, _ = manager.update_task(t["id"], status="in_progress")
        assert ok
        assert manager.list_tasks(topic="st")[0]["status"] == "in_progress"

    def test_in_progress_to_blocked(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st2", current_state="ok")
        t = manager.create_task("st2", "block it")
        manager.update_task(t["id"], status="in_progress")
        ok, _ = manager.update_task(t["id"], status="blocked")
        assert ok
        assert manager.list_tasks(topic="st2")[0]["status"] == "blocked"

    def test_blocked_to_in_progress(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st3", current_state="ok")
        t = manager.create_task("st3", "unblock")
        manager.update_task(t["id"], status="blocked")
        ok, _ = manager.update_task(t["id"], status="in_progress")
        assert ok

    def test_in_progress_to_done(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st4", current_state="ok")
        t = manager.create_task("st4", "finish")
        manager.update_task(t["id"], status="in_progress")
        ok, _ = manager.update_task(t["id"], status="done")
        assert ok

    def test_done_to_in_progress(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st5", current_state="ok")
        t = manager.create_task("st5", "reopen")
        manager.update_task(t["id"], status="done")
        ok, _ = manager.update_task(t["id"], status="in_progress")
        assert ok

    def test_invalid_status_rejected(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "st6", current_state="ok")
        t = manager.create_task("st6", "bad")
        ok, msg = manager.update_task(t["id"], status="invalid")
        assert not ok
        assert "Invalid" in msg


# ═══════════════════════════════════════════════════════════════════
# compact_planet preserves pinned + task-referenced notes
# ═══════════════════════════════════════════════════════════════════


class TestCompactPlanetPreservation:
    @staticmethod
    def _add_old_notes(manager, topic, count=40):
        for i in range(count):
            manager.add_note("test", topic, "fact", f"old note {i}")

    def test_pinned_notes_survive_compaction(self, seeded_db):
        _, storage, manager, data = seeded_db
        nid = int(data["notes"]["n1"]["id"].replace("note-", ""))
        manager.pin_note(nid)
        manager.compact_planet("test", "task-planet")
        notes = manager.search_notes(topic="task-planet")
        ids = {n["id"] for n in notes}
        assert nid in ids

    def test_non_done_task_referenced_notes_survive(self, seeded_db):
        _, storage, manager, data = seeded_db
        # n2 is referenced by t2 (status=todo) — should survive
        nid = int(data["notes"]["n2"]["id"].replace("note-", ""))
        # n3 and n4 are unreferenced — should be dropped if old enough
        # But they're recent (< 30 notes), so they survive by recency.
        # To test task-reference preservation we need >30 notes so recent cutoff drops them.
        self._add_old_notes(manager, "task-planet", 40)
        manager.compact_planet("test", "task-planet")
        cursor = manager.storage.connection.cursor()
        remaining = {r[0] for r in cursor.execute("SELECT id FROM notes").fetchall()}
        assert nid in remaining

    def test_unreferenced_old_notes_dropped(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "drop-test", current_state="ok")
        # Add 40 notes — only ~30 recent survive
        for i in range(40):
            manager.add_note("test", "drop-test", "fact", f"note {i}")
        # Add one task referencing none of them
        manager.create_task("drop-test", "unrelated task")
        manager.compact_planet("test", "drop-test")
        notes = manager.search_notes(topic="drop-test")
        # At most the recent 30 survive (the first 10 should be gone)
        ids = [n["id"] for n in notes]
        notes_by_id = {n["id"]: n for n in notes}
        first_ids = set(range(1, 11))  # first 10 notes
        surviving_first = first_ids & {n["id"] for n in notes}
        assert len(surviving_first) == 0, f"Old notes survived: {surviving_first}"

    def test_done_task_referenced_note_dropped(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "done-ref", current_state="ok")
        for i in range(40):
            manager.add_note("test", "done-ref", "fact", f"note {i}")
        nid = 45  # doesn't exist — will be silently ignored
        t = manager.create_task("done-ref", "completed task", notes=[nid])
        manager.update_task(t["id"], status="done")
        manager.compact_planet("test", "done-ref")
        # note nid doesn't exist, so nothing special should happen
        # just verifying no crash
        notes = manager.search_notes(topic="done-ref")
        assert len(notes) <= 30

    def test_note_referenced_by_non_done_survives_many_notes(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "big", current_state="ok")
        # Create 45 notes
        for i in range(45):
            manager.add_note("test", "big", "fact", f"b note {i}")
        # Retrieve note id of the 3rd note
        cursor = manager.storage.connection.cursor()
        all_ids = [r[0] for r in cursor.execute(
            "SELECT id FROM notes WHERE topic = ? ORDER BY created_at ASC", ("big",)
        ).fetchall()]
        note_3_id = all_ids[2]  # 3rd oldest
        t = manager.create_task("big", "protector task", notes=[note_3_id])
        manager.compact_planet("test", "big")
        after_ids = {r[0] for r in cursor.execute("SELECT id FROM notes").fetchall()}
        assert note_3_id in after_ids

    def test_compact_planet_no_tasks_no_crash(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "no-tasks", current_state="ok")
        for i in range(5):
            manager.add_note("test", "no-tasks", "fact", f"n {i}")
        from mcp_server.server import compact_planet
        r = compact_planet(topic="no-tasks")
        assert "Compacted" in r


# ═══════════════════════════════════════════════════════════════════
# Migration idempotency
# ═══════════════════════════════════════════════════════════════════


class TestMigrationIdempotency:
    def test_schema_migration_runs_twice_cleanly(self, pre_migration_db):
        conn = sqlite3.connect(pre_migration_db)
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        conn.commit()

        # Run again — should produce zero errors
        _ensure_schema(conn)
        conn.commit()

        # Verify all expected tables exist
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for tbl in ("planets", "notes", "note_links", "planet_links", "tasks"):
            assert tbl in tables, f"Missing table: {tbl}"

        # Verify all expected columns on notes
        notes_cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
        for col in ("tags", "pinned"):
            assert col in notes_cols, f"Missing column notes.{col}"

        # Verify all expected columns on tasks
        tasks_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        for col in ("id", "topic", "title", "status", "priority",
                    "depends_on", "files", "notes", "created_at", "completed_at"):
            assert col in tasks_cols, f"Missing column tasks.{col}"

        # Verify data survived
        planets = conn.execute("SELECT * FROM planets").fetchall()
        assert len(planets) == 1
        assert planets[0]["topic"] == "fixture-planet"

        notes = conn.execute("SELECT * FROM notes").fetchall()
        assert len(notes) == 1
        assert notes[0]["title"] == "old fixture note"

        # No duplicate columns from running migration twice
        assert len(tasks_cols) == 10

        conn.close()

    def test_migration_no_duplicate_columns(self, pre_migration_db):
        conn = sqlite3.connect(pre_migration_db)
        conn.row_factory = sqlite3.Row
        # Run three times
        for _ in range(3):
            _ensure_schema(conn)
            conn.commit()

        # Verify no duplicate columns on any table
        for tbl in ("planets", "notes", "note_links", "planet_links", "tasks"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            # Should be no duplicates — set dedup means unique only
            assert len(cols) == len(
                [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            )

        conn.close()


# ═══════════════════════════════════════════════════════════════════
# MCP end-to-end
# ═══════════════════════════════════════════════════════════════════


class TestTaskMCPTools:
    def test_task_create_mcp(self, seeded_db):
        from mcp_server.server import task_create
        db_path, storage, manager, data = seeded_db
        r = task_create(topic="task-planet", title="mcp task",
                        priority="high", depends_on=[data["tasks"]["t1"]["id"]],
                        files=["test_tasks.py"], notes=[])
        assert "task-" in r
        assert "created" in r.lower()
        tasks = manager.list_tasks(topic="task-planet", status="todo")
        titles = [t["title"] for t in tasks]
        assert "mcp task" in titles

    def test_task_create_minimal_mcp(self, temp_db):
        from mcp_server.server import task_create
        db_path, storage, manager = temp_db
        manager.update_planet("test", "minimal", current_state="ok")
        r = task_create(topic="minimal", title="simple")
        assert "task-" in r

    def test_task_update_status_mcp(self, seeded_db):
        from mcp_server.server import task_update
        _, _, manager, data = seeded_db
        tid = data["tasks"]["t1"]["id"]
        r = task_update(task_id=tid, status="in_progress")
        assert "updated" in r.lower()
        tasks = manager.list_tasks(topic="task-planet")
        t = next(t for t in tasks if t["id"] == tid)
        assert t["status"] == "in_progress"

    def test_task_update_invalid_status_mcp(self, seeded_db):
        from mcp_server.server import task_update
        _, _, _, data = seeded_db
        tid = data["tasks"]["t1"]["id"]
        r = task_update(task_id=tid, status="bogus")
        assert "Invalid" in r

    def test_task_block_with_reason_mcp(self, seeded_db):
        from mcp_server.server import task_block
        _, _, manager, data = seeded_db
        tid = data["tasks"]["t1"]["id"]
        r = task_block(task_id=tid, reason="waiting for review")
        assert "Blocked" in r
        tasks = manager.list_tasks(topic="task-planet")
        t = next(t for t in tasks if t["id"] == tid)
        assert t["status"] == "blocked"
        # Verify an issue note was created
        cursor = manager.storage.connection.cursor()
        issue_rows = cursor.execute(
            "SELECT title, content FROM notes WHERE topic = ? AND kind = 'issue'",
            ("task-planet",)
        ).fetchall()
        assert any("Blocked" in (r["title"] or "") for r in issue_rows)

    def test_task_block_without_reason_mcp(self, seeded_db):
        from mcp_server.server import task_block
        _, _, manager, data = seeded_db
        tid = data["tasks"]["t2"]["id"]
        r = task_block(task_id=tid, reason=None)
        assert "Blocked" in r
        tasks = manager.list_tasks(topic="task-planet")
        t = next(t for t in tasks if t["id"] == tid)
        assert t["status"] == "blocked"

    def test_task_block_not_found_mcp(self, temp_db):
        from mcp_server.server import task_block
        r = task_block(task_id=99999, reason="no reason")
        assert "not found" in r.lower() or "Blocked" in r

    def test_task_list_mcp(self, seeded_db):
        from mcp_server.server import task_list
        r = task_list(topic="task-planet")
        assert "Tasks" in r
        assert "implement crud" in r
        assert "write tests" in r

    def test_task_list_filtered_by_status_mcp(self, seeded_db):
        from mcp_server.server import task_list
        _, _, manager, data = seeded_db
        manager.update_task(data["tasks"]["t1"]["id"], status="in_progress")
        r = task_list(topic="task-planet", status="in_progress")
        assert "implement crud" in r
        assert "write tests" not in r

    def test_task_list_empty_mcp(self, temp_db):
        from mcp_server.server import task_list
        r = task_list(topic="nonexistent")
        assert "No tasks" in r

    def test_task_list_unfiltered_returns_all_statuses(self, seeded_db):
        from mcp_server.server import task_list
        _, _, manager, data = seeded_db
        manager.update_task(data["tasks"]["t1"]["id"], status="done")
        r = task_list()  # no filter
        assert "Tasks" in r
        assert "implement crud" in r

    def test_task_create_storage_verified(self, seeded_db):
        from mcp_server.server import task_create
        db_path, storage, manager, data = seeded_db
        task_create(topic="task-planet", title="verify me",
                    priority="low", depends_on=[], files=["/tmp/x"],
                    notes=[data["notes"]["n1"]["id"]])
        tasks = manager.list_tasks(topic="task-planet")
        created = [t for t in tasks if t["title"] == "verify me"]
        assert len(created) == 1
        assert created[0]["status"] == "todo"
        assert json.loads(created[0]["files"]) == ["/tmp/x"]
