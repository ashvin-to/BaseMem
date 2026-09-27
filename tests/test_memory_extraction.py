import json
import os
import tempfile

from storage.db import StorageManager
from storage.extraction import ExtractedMemory, HeuristicExtractor
from storage.sessions import SessionManager


def make_manager(tmpdir):
    storage = StorageManager(os.path.join(tmpdir, "test.db"))
    return SessionManager(storage)


def test_heuristic_distinguishes_modal_hypothesis_from_decision():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = make_manager(tmpdir)
        extracted = manager.auto_extract_memories(
            "BaseMem",
            "We might use Redis for caching.\nWe decided to use SQLite for storage.",
        )
        assert [item["type"] for item in extracted] == ["hypothesis", "decision"]
        assert [manager.get_note(item["note_id"])["kind"] for item in extracted] == ["hypothesis", "decision"]


def test_exact_duplicate_is_not_inserted_and_records_dedup_provenance():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = make_manager(tmpdir)
        first = manager.auto_extract_memories("BaseMem", "Decided: use SQLite for durable storage.")
        second = manager.auto_extract_memories("BaseMem", "  Decided: use SQLite for durable storage.  ")

        assert first[0]["dedup_status"] == "independent"
        assert second[0]["dedup_status"] == "exact_duplicate"
        assert second[0]["note_id"] == first[0]["note_id"]
        assert manager.get_note_count("BaseMem") == 1
        provenance = json.loads(manager.get_note(first[0]["note_id"])["provenance"])
        assert provenance["method"] == "heuristic"
        assert provenance["dedup"]["status"] == "independent"


def test_updated_contradiction_and_independent_candidates_are_distinguished():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = make_manager(tmpdir)
        manager.auto_extract_memories("BaseMem", "Decided: use PostgreSQL for the primary database.")
        updated = manager.auto_extract_memories(
            "BaseMem", "Decided: we now use SQLite for the primary database."
        )
        contradiction = manager.auto_extract_memories(
            "BaseMem", "Decided: we will not use SQLite for the primary database."
        )
        independent = manager.auto_extract_memories(
            "BaseMem", "Note: Redis handles transient caching."
        )

        assert updated[0]["dedup_status"] == "updated_version"
        assert contradiction[0]["dedup_status"] == "contradiction"
        assert independent[0]["dedup_status"] == "independent"
        assert manager.get_note_count("BaseMem") == 4


def test_near_duplicate_is_retained_with_near_duplicate_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = make_manager(tmpdir)
        first = manager.auto_extract_memories(
            "BaseMem", "Note: The API service listens on port 8000."
        )
        second = manager.auto_extract_memories(
            "BaseMem", "Note: The API service listens on port 8000 for requests."
        )

        assert first[0]["dedup_status"] == "independent"
        assert second[0]["dedup_status"] == "near_duplicate"
        assert second[0]["note_id"] != first[0]["note_id"]
        assert manager.get_note_count("BaseMem") == 2
        assert second[0]["provenance"]["dedup"]["matched_note_id"] is not None


def test_session_manager_accepts_extractor_interface():
    class FixedExtractor:
        def extract(self, text, agent_id="default"):
            return [ExtractedMemory(
                content="Fixed model extraction",
                kind="fact",
                type="fact",
                importance=0.7,
                confidence=0.8,
                source="model",
                provenance={"method": "model", "agent_id": agent_id},
            )]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(os.path.join(tmpdir, "test.db"))
        manager = SessionManager(storage, extractor=FixedExtractor())
        extracted = manager.auto_extract_memories("BaseMem", "ignored", agent_id="reviewer")

        assert extracted[0]["content"] == "Fixed model extraction"
        assert extracted[0]["provenance"]["method"] == "model"
        assert isinstance(HeuristicExtractor().extract("Decided: use SQLite"), list)
