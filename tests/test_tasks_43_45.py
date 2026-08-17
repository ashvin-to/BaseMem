"""Unit & integration tests for Tasks 43, 44, and 45."""

import os
import tempfile
from pathlib import Path
import pytest

from storage.db import StorageManager
from storage.sessions import SessionManager
from indexer.indexer import CodeIndexer
from indexer.watcher import CodeGraphWatcher


def test_task_43_auto_extract_memories_and_contradictions():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = StorageManager(db_path)
        manager = SessionManager(storage)

        # 1. Auto Memory Extraction
        sample_text = (
            "We discussed storage options for the project.\n"
            "Decided: Use SQLite as the primary database for BaseMem.\n"
            "Note: Set WAL mode for concurrency.\n"
        )
        extracted = manager.auto_extract_memories("BaseMem", sample_text)
        assert len(extracted) == 2
        types = [item["type"] for item in extracted]
        assert "decision" in types
        assert "fact" in types

        # 2. Contradiction Resolution
        manager.add_note("BaseMem", "basemem", "decision", "We decided to use PostgreSQL for main storage", title="PostgreSQL decision")
        manager.add_note("BaseMem", "basemem", "decision", "We decided to use SQLite instead of PostgreSQL for main storage", title="SQLite decision instead of PostgreSQL")

        res = manager.resolve_contradictions("BaseMem")
        assert res["resolved_count"] >= 1
        assert len(res["conflicts"]) >= 1


def test_task_44_watcher_sync_once():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "TestProject"
        p.mkdir()
        (p / "main.py").write_text("def run(): pass\n")

        indexer = CodeIndexer(str(p))
        indexer.index_project()

        watcher = CodeGraphWatcher(str(p), indexer)
        sync_res = watcher.sync_once()
        assert sync_res["status"] in ("synced", "unchanged")
        indexer.close()


def test_task_45_multi_layer_context_reranking():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = StorageManager(db_path)
        manager = SessionManager(storage)

        # Add sample notes
        n1 = manager.add_note("BaseMem", "basemem", "fact", "Tree-sitter parser implementation details", title="Tree-sitter Parser")
        n2 = manager.add_note("BaseMem", "basemem", "decision", "Decided to implement multi-layer context reranking combining FTS and graph distance", title="Context Re-Ranking Decision")

        # Link notes to give n2 higher graph connectivity
        n1_id = manager._parse_note_id(n1["id"])
        n2_id = manager._parse_note_id(n2["id"])
        if n1_id and n2_id:
            manager.link_notes(n1_id, n2_id, weight=0.9)

        ranked = manager.rank_context("BaseMem", query="reranking graph")
        assert len(ranked) == 2
        assert "score" in ranked[0]
        assert "fts_score" in ranked[0]
        assert "graph_score" in ranked[0]
        assert "recency_score" in ranked[0]
        # Re-ranked top result should be n2 because query tokens match n2's title/content
        assert ranked[0]["id"] == n2_id
