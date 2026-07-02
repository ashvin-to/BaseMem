"""Tests for Flask API endpoints (server.py)"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from server import app


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        orig_testing = app.config.get("TESTING")
        app.config["TESTING"] = True

        import sqlite3
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        from storage.sessions import _ensure_schema
        _ensure_schema(conn)
        conn.close()

        with patch("server._storage", None), \
             patch("server._db_path", return_value=db_path), app.test_client() as c:
            yield c

        app.config["TESTING"] = orig_testing


class TestIndex:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["service"] == "BaseMem"
        assert "planets" in data["endpoints"]


class TestPlanets:
    def test_list_empty(self, client):
        resp = client.get("/api/planets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["planets"] == []

    def test_create_and_get(self, client):
        create = client.post("/api/planets", json={
            "topic": "test-planet",
            "goal": "testing api",
            "status": "active",
        })
        assert create.status_code == 200
        assert create.get_json()["status"] == "success"

        resp = client.get("/api/planets/test-planet")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["topic"] == "test-planet"
        assert data["goal"] == "testing api"

    def test_get_not_found(self, client):
        resp = client.get("/api/planets/nonexistent")
        assert resp.status_code == 404

    def test_create_missing_topic(self, client):
        resp = client.post("/api/planets", json={"goal": "no topic"})
        assert resp.status_code == 400

    def test_delete(self, client):
        client.post("/api/planets", json={"topic": "delete-me"})
        resp = client.delete("/api/planets/delete-me")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == "delete-me"

        get = client.get("/api/planets/delete-me")
        assert get.status_code == 404


class TestNotes:
    def test_add_and_get(self, client):
        client.post("/api/planets", json={"topic": "my-planet"})
        add = client.post("/api/notes", json={
            "topic": "my-planet",
            "kind": "fact",
            "content": "hello world",
            "title": "test note",
        })
        assert add.status_code == 200
        note = add.get_json()["note"]
        assert note["content"] == "hello world"

        note_id = int(note["id"].replace("note-", ""))
        detail = client.get(f"/api/notes/{note_id}")
        assert detail.status_code == 200
        assert detail.get_json()["note"]["content"] == "hello world"

    def test_add_missing_fields(self, client):
        resp = client.post("/api/notes", json={"topic": "x"})
        assert resp.status_code == 400

    def test_get_note_not_found(self, client):
        resp = client.get("/api/notes/99999")
        assert resp.status_code == 404

    def test_note_neighbors(self, client):
        client.post("/api/planets", json={"topic": "graph-test"})
        n1 = client.post("/api/notes", json={
            "topic": "graph-test", "kind": "fact", "content": "A",
        }).get_json()["note"]
        n2 = client.post("/api/notes", json={
            "topic": "graph-test", "kind": "fact", "content": "B",
        }).get_json()["note"]

        from server import get_session
        conn = get_session().storage.connection
        id1 = int(n1["id"].replace("note-", ""))
        id2 = int(n2["id"].replace("note-", ""))
        conn.execute(
            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, source) VALUES (?, ?, 'related', 0.5, 'test')",
            (id1, id2),
        )
        conn.commit()

        detail = client.get(f"/api/notes/{id1}")
        assert detail.status_code == 200
        assert len(detail.get_json()["neighbors"]) >= 1


class TestSession:
    def test_session_turn(self, client):
        client.post("/api/planets", json={"topic": "chat"})
        resp = client.post("/api/session/turn", json={
            "topic": "chat",
            "message": "hello",
            "agent_id": "tester",
            "sender": "user",
        })
        assert resp.status_code == 200
        assert resp.get_json()["logged"] is True

    def test_session_turn_with_summary(self, client):
        client.post("/api/planets", json={"topic": "chat2"})
        resp = client.post("/api/session/turn", json={
            "topic": "chat2",
            "message": "do something",
            "summary": "we did something",
        })
        assert resp.status_code == 200

    def test_session_turn_missing_fields(self, client):
        resp = client.post("/api/session/turn", json={"topic": "x"})
        assert resp.status_code == 400

    def test_session_read(self, client):
        client.post("/api/planets", json={"topic": "read-test", "goal": "read goal"})
        resp = client.get("/api/session/read/read-test")
        assert resp.status_code == 200
        assert "read goal" in resp.get_json()["content"]

    def test_session_read_not_found(self, client):
        resp = client.get("/api/session/read/ghost")
        assert resp.status_code == 404


class TestGraph:
    def test_notes_graph_empty(self, client):
        resp = client.get("/api/notes/graph")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_project_graph(self, client):
        client.post("/api/planets", json={"topic": "my-proj"})
        client.post("/api/notes", json={
            "topic": "my-proj", "kind": "fact", "content": "note x",
        })
        resp = client.get("/api/graph/my-proj")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["nodes"]) >= 1  # planet + note
        assert data["stats"]["planets"] == 1


class TestSearch:
    def test_search_empty_query(self, client):
        resp = client.get("/api/search")
        assert resp.status_code == 200
        assert resp.get_json()["results"] == []

    def test_search_finds_planet(self, client):
        client.post("/api/planets", json={"topic": "unique-search-target"})
        resp = client.get("/api/search?q=unique-search")
        assert resp.status_code == 200
        results = resp.get_json()["results"]
        assert any(r["type"] == "planet" for r in results)

    def test_search_finds_note(self, client):
        client.post("/api/planets", json={"topic": "snote"})
        client.post("/api/notes", json={
            "topic": "snote", "kind": "fact", "content": "very specific search content test",
        })
        resp = client.get("/api/search?q=very+specific+search")
        assert resp.status_code == 200
        results = resp.get_json()["results"]
        assert any(r["type"] == "note" for r in results)


class TestLinks:
    def test_link_planets(self, client):
        client.post("/api/planets", json={"topic": "alpha"})
        client.post("/api/planets", json={"topic": "beta"})
        resp = client.post("/api/planet-links", json={
            "from_planet": "alpha",
            "to_planet": "beta",
            "relation": "related",
        })
        assert resp.status_code == 200

    def test_get_planet_links(self, client):
        client.post("/api/planets", json={"topic": "gamma"})
        client.post("/api/planets", json={"topic": "delta"})
        client.post("/api/planet-links", json={
            "from_planet": "gamma", "to_planet": "delta",
        })
        resp = client.get("/api/planet-links/gamma")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["links"]) >= 1

    def test_recompute_links(self, client):
        client.post("/api/planets", json={"topic": "recomp"})
        client.post("/api/notes", json={
            "topic": "recomp", "kind": "fact", "content": "hello world",
        })
        client.post("/api/notes", json={
            "topic": "recomp", "kind": "fact", "content": "hello world again",
        })
        resp = client.post("/api/recompute-links", json={"threshold": 0.01})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"


class TestEdgeDecayPrune:
    def test_edge_decay(self, client):
        client.post("/api/planets", json={"topic": "edges"})
        n1 = client.post("/api/notes", json={
            "topic": "edges", "kind": "fact", "content": "A",
        }).get_json()["note"]
        n2 = client.post("/api/notes", json={
            "topic": "edges", "kind": "fact", "content": "B",
        }).get_json()["note"]
        from server import get_session
        conn = get_session().storage.connection
        conn.execute(
            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, source) VALUES (?, ?, 'auto', 0.5, 'auto')",
            (int(n1["id"].replace("note-", "")), int(n2["id"].replace("note-", ""))),
        )
        conn.commit()

        resp = client.post("/api/edge/decay", json={"factor": 0.8})
        assert resp.status_code == 200

    def test_edge_prune(self, client):
        client.post("/api/planets", json={"topic": "prune"})
        n1 = client.post("/api/notes", json={
            "topic": "prune", "kind": "fact", "content": "X",
        }).get_json()["note"]
        n2 = client.post("/api/notes", json={
            "topic": "prune", "kind": "fact", "content": "Y",
        }).get_json()["note"]
        from server import get_session
        conn = get_session().storage.connection
        conn.execute(
            "INSERT INTO note_links (from_note_id, to_note_id, link_type, weight, source) VALUES (?, ?, 'auto', 0.01, 'auto')",
            (int(n1["id"].replace("note-", "")), int(n2["id"].replace("note-", ""))),
        )
        conn.commit()

        resp = client.post("/api/edge/prune", json={"threshold": 0.05})
        assert resp.status_code == 200


class TestExportImport:
    def test_export_and_import(self, client):
        client.post("/api/planets", json={"topic": "exim", "goal": "test"})
        client.post("/api/notes", json={
            "topic": "exim", "kind": "fact", "content": "export me",
        })

        export = client.get("/api/export")
        assert export.status_code == 200
        data = export.get_json()
        assert "planets" in data
        assert "notes" in data

        import_resp = client.post("/api/import", json=data)
        assert import_resp.status_code == 200
        result = import_resp.get_json()
        assert result["status"] == "success"
