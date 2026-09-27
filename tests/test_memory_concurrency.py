from __future__ import annotations

import sqlite3

from tests.concurrency_helpers import make_manager, make_managers, run_together

TOPIC = "concurrency"
SEED = "seed memory for concurrent readers"


def test_ten_concurrent_readers(tmp_path):
    db_path = tmp_path / "readers.db"
    setup = make_manager(db_path)
    seed = setup.create_note(TOPIC, "FACT", SEED)
    managers = make_managers(db_path, 10)

    results = run_together(10, lambda index: managers[index].get_note(seed["id"]))

    assert all(result and result["content"] == SEED for result in results)


def test_five_concurrent_writers_preserve_every_write(tmp_path):
    db_path = tmp_path / "writers.db"
    setup = make_manager(db_path)
    setup.create_note(TOPIC, "FACT", "initialize planet")
    managers = make_managers(db_path, 5)

    def write(index):
        content = f"writer-{index} unique payload"
        result = managers[index].create_note(TOPIC, "FACT", content)
        return result["id"], content

    writes = run_together(5, write)
    verification = make_manager(db_path)
    rows = verification.list_notes(TOPIC, limit=100)
    contents = [row["content"] for row in rows]

    assert len({note_id for note_id, _ in writes}) == 5
    assert {content for _, content in writes} <= set(contents)
    assert len(contents) == len(set(contents))
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_mixed_readers_and_writers(tmp_path):
    db_path = tmp_path / "mixed.db"
    setup = make_manager(db_path)
    seed = setup.create_note(TOPIC, "FACT", SEED)
    managers = make_managers(db_path, 10)

    def work(index):
        if index % 2:
            content = f"mixed writer {index}"
            managers[index].create_note(TOPIC, "FACT", content)
            return "write", content
        return "read", managers[index].get_note(seed["id"])["content"]

    results = run_together(10, work)
    verification = make_manager(db_path)
    contents = {row["content"] for row in verification.list_notes(TOPIC, limit=100)}

    assert [result[0] for result in results].count("read") == 5
    assert [result[0] for result in results].count("write") == 5
    assert {content for operation, content in results if operation == "write"} <= contents
    assert all(content == SEED for operation, content in results if operation == "read")


def test_context_retrieval_and_insertion_run_together(tmp_path):
    db_path = tmp_path / "context.db"
    setup = make_manager(db_path)
    setup.create_note(TOPIC, "FACT", "context marker baseline")
    managers = make_managers(db_path, 8)

    def retrieve(index):
        if index % 2:
            managers[index].create_note(TOPIC, "FACT", f"context insert writer {index}")
            return "write", index
        context = managers[index].compile_context(TOPIC, "context marker")
        return "read", context

    results = run_together(8, retrieve)
    verification = make_manager(db_path)
    contents = {row["content"] for row in verification.list_notes(TOPIC, limit=100)}
    contexts = [payload for operation, payload in results if operation == "read"]
    expected_writes = {f"context insert writer {index}" for index in range(1, 8, 2)}

    assert all(context["ranked"] and context["token_count"] > 0 for context in contexts)
    assert expected_writes <= contents
    assert verification.storage.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
