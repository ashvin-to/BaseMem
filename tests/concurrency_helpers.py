from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import TypeVar

from storage.db import StorageManager
from storage.sessions import SessionManager

T = TypeVar("T")
BUSY_TIMEOUT_MS = 250


def make_manager(db_path: Path) -> SessionManager:
    storage = StorageManager(str(db_path))
    storage.connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return SessionManager(storage)


def make_managers(db_path: Path, count: int) -> list[SessionManager]:
    managers = [make_manager(db_path) for _ in range(count)]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    return managers


def run_together(worker_count: int, worker: Callable[[int], T]) -> list[T]:
    barrier = Barrier(worker_count)

    def run(index: int) -> T:
        barrier.wait(timeout=5)
        return worker(index)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return [future.result(timeout=10) for future in [executor.submit(run, index) for index in range(worker_count)]]
