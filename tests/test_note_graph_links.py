import tempfile
from pathlib import Path

from storage.db import StorageManager
from storage.migrations import run_migrations
from storage.notes import NoteLink, NoteRelation
from storage.sessions import SessionManager


def _manager(monkeypatch):
    temp_dir = tempfile.TemporaryDirectory()
    storage = StorageManager(str(Path(temp_dir.name) / "graph.db"))
    storage.connection.commit()
    monkeypatch.setattr("storage.sessions.run_migrations", lambda connection: (connection.commit(), run_migrations(connection))[1])
    return SessionManager(storage), storage, temp_dir


def test_note_links_preserve_direction_and_typed_relations(monkeypatch):
    manager, storage, temp_dir = _manager(monkeypatch)
    try:
        first = manager.add_note("", "graph", "fact", "first note", scope="api")
        second = manager.add_note("", "graph", "fact", "second note", scope="api")
        assert manager.link_notes(first["id"], second["id"], link_type=NoteRelation.SUPERSEDES, confidence=0.8,
                                  provenance={"source": "test"}, created_at="2026-01-01T00:00:00")
        out = manager.get_note_neighbors(first["id"], direction="out")
        incoming = manager.get_note_neighbors(second["id"], direction="in")
        both = manager.get_note_neighbors(second["id"])
        assert out[0]["id"] == int(second["id"].removeprefix("note-"))
        assert out[0]["relation"] == NoteRelation.SUPERSEDES.value
        assert incoming[0]["id"] == int(first["id"].removeprefix("note-"))
        assert both[0]["direction"] == "in"
        row = storage.connection.execute(
            "SELECT from_note_id, to_note_id, link_type, confidence, provenance, created_at FROM note_links"
        ).fetchone()
        assert (row["from_note_id"], row["to_note_id"]) == (int(first["id"][5:]), int(second["id"][5:]))
        assert row["confidence"] == 0.8
        assert '"test"' in row["provenance"]
        assert row["created_at"] == "2026-01-01T00:00:00"
        assert NoteLink.from_row(row).relation == "supersedes"
    finally:
        storage.close()
        temp_dir.cleanup()


def test_retrieval_exposes_link_metadata_and_auto_links_are_lexical(monkeypatch):
    manager, storage, temp_dir = _manager(monkeypatch)
    try:
        first = manager.add_note("", "graph", "fact", "alpha beta gamma delta", scope="same", source_path="entity-a")
        manager.add_note("", "graph", "fact", "alpha beta gamma delta", scope="same", source_path="entity-a")
        neighbors = manager.get_note_neighbors(first["id"])
        assert neighbors
        assert neighbors[0]["link_type"] == "lexical_related"
        assert neighbors[0]["relation"] == "lexical_related"
        assert neighbors[0]["source"] == "auto"
        assert '"semantic": false' in neighbors[0]["provenance"]
    finally:
        storage.close()
        temp_dir.cleanup()


def test_auto_links_do_not_cross_scopes_or_entities(monkeypatch):
    manager, storage, temp_dir = _manager(monkeypatch)
    try:
        first = manager.add_note("", "graph", "fact", "shared lexical words", scope="one", source_path="a")
        manager.add_note("", "graph", "fact", "shared lexical words", scope="two", source_path="b")
        assert manager.get_note_neighbors(first["id"]) == []
    finally:
        storage.close()
        temp_dir.cleanup()
