"""Tests for session CRUD, auto-recovery, note/task stamping,
context block rendering, and MCP tool end-to-end."""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from storage.db import StorageManager
from storage.sessions import SessionManager


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        os.environ["BASEMEM_DB_PATH"] = str(db_path)
        storage = StorageManager(str(db_path))
        manager = SessionManager(storage)
        yield db_path, storage, manager
        storage.close()
        del os.environ["BASEMEM_DB_PATH"]


class TestSessionCRUD:
    def test_create_session_returns_valid_active_session(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "my-planet", current_state="ok")
        sid = manager.create_session("my-planet", "Test Sprint", agent_id="agent-x")
        assert sid > 0
        s = manager.get_session(sid)
        assert s["title"] == "Test Sprint"
        assert s["topic"] == "my-planet"
        assert s["status"] == "active"
        assert s["agent_id"] == "agent-x"
        assert s["started_at"] is not None
        assert s["last_active_at"] is not None
        assert s["ended_at"] is None
        assert s["summary"] is None
        assert json.loads(s["note_ids"]) == []
        assert json.loads(s["task_ids"]) == []

    def test_get_session_nonexistent(self, temp_db):
        _, storage, manager = temp_db
        assert manager.get_session(999) is None

    def test_close_session_sets_status_and_summary(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        ok = manager.close_session(sid, summary="Done")
        assert ok is True
        s = manager.get_session(sid)
        assert s["status"] == "closed"
        assert s["summary"] == "Done"
        assert s["ended_at"] is not None

    def test_close_session_no_summary_sets_ended_at(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        ok = manager.close_session(sid)
        assert ok is True
        s = manager.get_session(sid)
        assert s["status"] == "closed"
        assert s["summary"] is None
        assert s["ended_at"] is not None

    def test_close_session_nonexistent_returns_false(self, temp_db):
        _, storage, manager = temp_db
        assert manager.close_session(999) is False

    def test_pause_and_resume_session(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        ok = manager.pause_session(sid)
        assert ok is True
        s = manager.get_session(sid)
        assert s["status"] == "paused"

        ok = manager.resume_session(sid, agent_id="agent-y")
        assert ok is True
        s = manager.get_session(sid)
        assert s["status"] == "active"
        assert s["agent_id"] == "agent-y"

    def test_pause_resume_nonexistent_returns_false(self, temp_db):
        _, storage, manager = temp_db
        assert manager.pause_session(999) is False
        assert manager.resume_session(999, agent_id="default") is False

    def test_list_sessions_filters_by_topic_and_status(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        s1 = manager.create_session("p", "Sprint A", agent_id="default")
        s2 = manager.create_session("p", "Sprint B", agent_id="default")
        manager.close_session(s1)

        all_ = manager.list_sessions("p")
        assert len(all_) == 2

        active = manager.list_sessions("p", status="active")
        assert len(active) == 1
        assert active[0]["id"] == s2

        closed = manager.list_sessions("p", status="closed")
        assert len(closed) == 1
        assert closed[0]["id"] == s1

    def test_list_sessions_unknown_topic_returns_empty(self, temp_db):
        _, storage, manager = temp_db
        assert manager.list_sessions("ghost") == []


class TestNoteTaskStamping:
    def test_stamp_note_appends_and_is_idempotent(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        n = manager.add_note("note-1", "p", "fact", "hello")
        nid = int(n["id"].replace("note-", ""))

        manager.stamp_note(sid, nid)
        s = manager.get_session(sid)
        assert json.loads(s["note_ids"]) == [nid]

        manager.stamp_note(sid, nid)
        s = manager.get_session(sid)
        assert json.loads(s["note_ids"]) == [nid]

    def test_stamp_task_appends(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        t = manager.create_task("p", "do something")
        tid = t["id"]

        manager.stamp_task(sid, tid)
        s = manager.get_session(sid)
        assert json.loads(s["task_ids"]) == [tid]

    def test_add_note_stamps_session_id_when_active_session_exists(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        n = manager.add_note("note-1", "p", "fact", "stamped")
        nid = int(n["id"].replace("note-", ""))

        cursor = storage.connection.cursor()
        row = cursor.execute("SELECT session_id FROM notes WHERE id=?", (nid,)).fetchone()
        assert row["session_id"] == sid

    def test_add_note_leaves_session_id_null_when_no_active_session(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        n = manager.add_note("note-1", "p", "fact", "no session")
        nid = int(n["id"].replace("note-", ""))

        cursor = storage.connection.cursor()
        row = cursor.execute("SELECT session_id FROM notes WHERE id=?", (nid,)).fetchone()
        assert row["session_id"] is None

    def test_add_note_no_stamp_for_different_agent(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        manager.create_session("p", "Sprint", agent_id="agent-a")
        n = manager.add_note("note-1", "p", "fact", "different agent", agent_id="agent-b")
        nid = int(n["id"].replace("note-", ""))
        cursor = storage.connection.cursor()
        row = cursor.execute("SELECT session_id FROM notes WHERE id=?", (nid,)).fetchone()
        assert row["session_id"] is None

    def test_create_task_stamps_session_id_when_active(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        t = manager.create_task("p", "task with session")
        cursor = storage.connection.cursor()
        row = cursor.execute("SELECT session_id FROM tasks WHERE id=?", (t["id"],)).fetchone()
        assert row["session_id"] == sid

    def test_create_task_no_stamp_when_no_active_session(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        t = manager.create_task("p", "task without session")
        cursor = storage.connection.cursor()
        row = cursor.execute("SELECT session_id FROM tasks WHERE id=?", (t["id"],)).fetchone()
        assert row["session_id"] is None

    def test_parallel_agent_sessions_dont_interfere(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        manager.create_session("p", "Agent A work", agent_id="agent-a")
        manager.create_session("p", "Agent B work", agent_id="agent-b")

        na = manager.add_note("note-a", "p", "fact", "from A", agent_id="agent-a")
        nb = manager.add_note("note-b", "p", "fact", "from B", agent_id="agent-b")

        cursor = storage.connection.cursor()
        ra = cursor.execute("SELECT session_id FROM notes WHERE id=?",
                            (int(na["id"].replace("note-", "")),)).fetchone()
        rb = cursor.execute("SELECT session_id FROM notes WHERE id=?",
                            (int(nb["id"].replace("note-", "")),)).fetchone()
        assert ra["session_id"] is not None
        assert rb["session_id"] is not None
        assert ra["session_id"] != rb["session_id"]


class TestAutoRecover:
    def test_auto_recover_pauses_stale_sessions(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")

        os.environ["BASEMEM_SESSION_TIMEOUT_HOURS"] = "1"
        sid = manager.create_session("p", "Old Sprint", agent_id="default")

        cursor = storage.connection.cursor()
        past = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cursor.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (past, sid))
        storage.connection.commit()

        changed = manager.auto_recover_sessions("p")
        s = manager.get_session(sid)
        assert s["status"] == "paused"
        assert sid in changed

        notes = cursor.execute(
            "SELECT content FROM notes WHERE topic='p' AND kind='fact' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert notes is not None
        assert "auto-recovered" in notes["content"]

    def test_auto_recover_preserves_recent_sessions(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        os.environ["BASEMEM_SESSION_TIMEOUT_HOURS"] = "1"

        sid = manager.create_session("p", "Recent Sprint", agent_id="default")
        changed = manager.auto_recover_sessions("p")
        assert sid not in changed
        s = manager.get_session(sid)
        assert s["status"] == "active"

    def test_auto_recover_only_targets_topic(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p1", current_state="ok")
        manager.update_planet("test", "p2", current_state="ok")
        os.environ["BASEMEM_SESSION_TIMEOUT_HOURS"] = "1"

        old_sid = manager.create_session("p1", "Old", agent_id="default")
        manager.create_session("p2", "Recent", agent_id="default")

        cursor = storage.connection.cursor()
        past = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cursor.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (past, old_sid))
        storage.connection.commit()

        changed_one = manager.auto_recover_sessions("p1")
        assert old_sid in changed_one

        changed_two = manager.auto_recover_sessions("p2")
        assert changed_two == []

    def test_get_session_updates_last_active_at(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        sid = manager.create_session("p", "Sprint", agent_id="default")
        s_before = manager.get_session(sid)
        last_before = s_before["last_active_at"]

        s_after = manager.get_session(sid)
        assert s_after["last_active_at"] >= last_before


class TestContextBlock:
    def test_get_context_includes_sessions_block(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        manager.create_session("p", "Active Sprint", agent_id="agent-x")
        ctx = manager.get_context("p")
        assert "Active Sprint" in ctx
        assert "agent-x" in ctx
        assert "active, last" in ctx

    def test_get_context_shows_last_closed_summary(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        s1 = manager.create_session("p", "Sprint 1", agent_id="default")
        manager.close_session(s1, summary="All done")
        manager.create_session("p", "Sprint 2", agent_id="default")

        ctx = manager.get_context("p")
        assert "last session:" in ctx
        assert "All done" in ctx

    def test_get_context_last_closed_shows_note_titles_when_no_summary(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        s1 = manager.create_session("p", "Sprint 1", agent_id="default")
        n1 = manager.add_note("n1", "p", "fact", "first note content")
        n2 = manager.add_note("n2", "p", "fact", "second note content")
        nid1 = int(n1["id"].replace("note-", ""))
        nid2 = int(n2["id"].replace("note-", ""))
        manager.stamp_note(s1, nid1)
        manager.stamp_note(s1, nid2)
        manager.close_session(s1)

        manager.create_session("p", "Sprint 2", agent_id="default")
        ctx = manager.get_context("p")
        assert "last session note:" in ctx
        assert "first note content" in ctx
        assert "second note content" in ctx

    def test_build_agent_context_includes_sessions_block(self, temp_db):
        _, storage, manager = temp_db
        manager.update_planet("test", "p", current_state="ok")
        manager.create_session("p", "Live Session", agent_id="agent-x")
        ctx = manager.build_agent_context("p")
        assert "Live Session" in ctx
        assert "active" in ctx
