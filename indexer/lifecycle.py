import json
import os
import subprocess
import sys
from pathlib import Path

from .indexer import CODE_DB_FILENAME, CodeIndexer, _PARALLEL_MIN_FILES

# Above this many files, building the index is an explicit act, never a side effect
# of asking a question. A tool call that indexes a whole disk is never what the
# caller meant, and it cannot be undone quickly.
MAX_AUTO_INDEX_FILES = 20_000

# Indexing from inside the MCP server used to fork a process pool out of an
# already-threaded, already-database-connected process, which deadlocked on a
# futex and wedged the server for the rest of the session. Doing it in a fresh
# subprocess removes that entirely: the parent never forks.
AUTO_INDEX_TIMEOUT_S = 3600


class AutoIndexRefused(RuntimeError):
    """Raised when a query would trigger an index too large to build implicitly."""


def _count_indexable_files(root: Path) -> int:
    """Count indexable files without opening the database.

    Deliberately does not construct a CodeIndexer: its constructor creates the
    schema, and an empty .basemem.code.db left behind by a refused auto-index
    would make the next call believe an index already exists. This walk also
    skips gitignore filtering, so it over-counts slightly, which is the safe
    direction for a limit.
    """
    from .indexer import SKIP_EXTENSIONS
    from .parser import CodeParser

    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue
            if CodeParser.supported_extension(ext):
                n += 1
    return n


def _index_in_subprocess(root: str, max_workers: int) -> dict | None:
    """Build the index in a separate process, never in the caller's.

    Returns the indexer's own counts, so a caller that reports progress does not
    have to reopen the database to learn them.
    """
    script = (
        "import json;"
        "from indexer.indexer import CodeIndexer;"
        f"ix = CodeIndexer({root!r});"
        f"r = ix.index_project(_max_workers={max_workers});"
        "ix.close();"
        "print(json.dumps({'files': r['files'], 'symbols': r['symbols'],"
        " 'edges': r['edges'], 'elapsed': r['elapsed']}))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=AUTO_INDEX_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise AutoIndexRefused(
            f"auto-index exceeded {AUTO_INDEX_TIMEOUT_S}s and was stopped; "
            f"build it explicitly with: mem code init {root}"
        ) from None
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(
            "auto-index failed: " + (tail[-1] if tail else f"exit {proc.returncode}")
        )
    for line in reversed((proc.stdout or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def open_or_create_index(project_root: str, max_workers: int = 4) -> CodeIndexer:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    if not (root / CODE_DB_FILENAME).exists():
        count = _count_indexable_files(root)
        if count > MAX_AUTO_INDEX_FILES:
            raise AutoIndexRefused(
                f"{root} has {count:,} indexable files, over the "
                f"{MAX_AUTO_INDEX_FILES:,} limit, so it is not indexed implicitly. "
                f"Run: mem code init {root}"
            )
        if max_workers > 1 and count >= _PARALLEL_MIN_FILES:
            _index_in_subprocess(str(root), max_workers)
        else:
            indexer = CodeIndexer(str(root))
            try:
                indexer.index_project(_max_workers=max_workers)
            finally:
                indexer.close()
    return CodeIndexer(str(root))