from pathlib import Path

from .indexer import CODE_DB_FILENAME, CodeIndexer


def open_or_create_index(project_root: str, max_workers: int = 4) -> CodeIndexer:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    if not (root / CODE_DB_FILENAME).exists():
        indexer = CodeIndexer(str(root))
        try:
            indexer.index_project(_max_workers=max_workers)
        finally:
            indexer.close()
    return CodeIndexer(str(root))
