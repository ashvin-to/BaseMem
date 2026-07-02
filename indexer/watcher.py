"""File system watcher for auto-syncing code graph."""

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from .indexer import SKIP_DIRS
from .parser import CodeParser

logger = logging.getLogger(__name__)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer as _Observer
    HAS_WATCHDOG = True
    Observer = _Observer
except ImportError:
    Observer = None  # type: ignore[assignment]
    HAS_WATCHDOG = False


class CodeGraphEventHandler(FileSystemEventHandler):
    """Handles file system events for code graph sync."""

    def __init__(self, root_path: str, on_change: Callable[[list[str], list[str], list[str]], None]):
        super().__init__()
        self.root_path = root_path
        self.on_change = on_change
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._pending_changes: dict = {"modified": [], "created": [], "deleted": []}
        self._debounce_seconds = 2.0

    def on_modified(self, event):
        if event.is_directory:
            return
        if self._is_source_file(event.src_path):
            self._queue("modified", event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if self._is_source_file(event.src_path):
            self._queue("created", event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        if self._is_source_file(event.src_path):
            self._queue("deleted", event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        if self._is_source_file(event.dest_path):
            self._queue("created", event.dest_path)
        if self._is_source_file(event.src_path):
            self._queue("deleted", event.src_path)

    def _is_source_file(self, path: str) -> bool:
        p = Path(path)
        if any(part in SKIP_DIRS for part in p.parts):
            return False
        return CodeParser.supported_extension(p.suffix.lower())

    def _queue(self, kind: str, path: str):
        with self._lock:
            rel = os.path.relpath(path, self.root_path)
            if rel not in self._pending_changes[kind]:
                self._pending_changes[kind].append(rel)
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self._debounce_seconds, self._flush)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _flush(self):
        with self._lock:
            changes = self._pending_changes
        self._pending_changes: dict[str, list[str]] = {"modified": [], "created": [], "deleted": []}
        if any(changes.values()):
            try:
                self.on_change(
                    changes.get("modified", []),
                    changes.get("created", []),
                    changes.get("deleted", []),
                )
            except Exception as e:
                logger.error(f"Error in code graph change handler: {e}")


class CodeGraphWatcher:
    """Watches a directory for source file changes and syncs the code graph."""

    def __init__(self, root_path: str, indexer, auto_start: bool = False):
        self.root_path = root_path
        self.indexer = indexer
        self._observer: Observer | None = None  # type: ignore[valid-type]
        self._running = False

        if auto_start:
            self.start()

    def start(self):
        if not HAS_WATCHDOG:
            logger.warning("watchdog not installed. Code graph auto-sync disabled.")
            return
        if self._running:
            return

        event_handler = CodeGraphEventHandler(
            self.root_path,
            on_change=self._handle_change,
        )
        self._observer = Observer()
        self._observer.schedule(event_handler, self.root_path, recursive=True)
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        logger.info(f"Code graph watcher started on {self.root_path}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._running = False
            logger.info("Code graph watcher stopped")

    def _is_skipped(self, path: str) -> bool:
        return any(f"/{d}/" in f"/{path}/" for d in SKIP_DIRS)

    def _handle_change(self, modified: list, created: list, deleted: list):
        if deleted:
            for f in deleted:
                if self._is_skipped(f):
                    continue
                self.indexer.remove_file(f)
                print(f"  [del] {f}")

        to_index = [f for f in (modified + created) if not self._is_skipped(f)]
        if to_index:
            result = self.indexer.index_files(self.root_path, to_index)
            for f in to_index:
                print(f"  [mod] {f}")
            print(f"  -> {result['symbols_added']} symbols, {result['edges_added']} edges")
