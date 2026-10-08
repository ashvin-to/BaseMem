"""No MCP tool may build the index in-process.

Indexing forks a process pool. Doing that from inside the MCP server, which
already holds the project's sqlite connection, hands the children an inherited
connection they cannot use: the whole tree -- server, workers and the calling
agent -- blocks in `futex_do_wait` and the server is dead for the session. It
happened on a 13,341-file repo, leaving the index at 642 of 13,341 files.

Commit 00eafcd fixed this for the auto-index paths by building in a subprocess
(`indexer/lifecycle.py`). Three tools kept hand-rolling the old shape and
reintroduced it: `code_init`, `code_find` and `code_explore`.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import mcp_server.server as srv  # noqa: E402
from indexer.lifecycle import _index_in_subprocess  # noqa: E402


def test_server_never_indexes_in_process():
    """Any `index_project(` in the server is a fork waiting to happen."""
    source = (REPO_ROOT / "mcp_server" / "server.py").read_text()
    # Ignore comments, which legitimately name the function while explaining it.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert not re.search(r"\.index_project\(", code), (
        "mcp_server/server.py calls index_project in-process; use "
        "indexer.lifecycle._index_in_subprocess so the parent never forks"
    )


def _code_init():
    """`@server.tool` wraps the function, so reach through to the real one."""
    return next(t.fn for t in srv._tool_manager.list_tools() if t.name == "code_init")


def test_code_init_does_not_open_an_indexer():
    import inspect

    src = inspect.getsource(_code_init())
    assert "CodeIndexer" not in src
    assert "_index_in_subprocess" in src


def test_subprocess_build_reports_the_counts(tmp_path):
    (tmp_path / "lib.py").write_text("def a():\n    return b()\n\n\ndef b():\n    return 1\n")
    result = _index_in_subprocess(str(tmp_path), 1)
    assert result is not None
    assert result["files"] >= 1
    assert result["symbols"] >= 2
    assert result["edges"] >= 1
    assert result["elapsed"] >= 0


def test_code_init_reports_counts(tmp_path):
    (tmp_path / "lib.py").write_text("def a():\n    return b()\n\n\ndef b():\n    return 1\n")
    out = _code_init()(str(tmp_path))
    assert out.startswith("code_init ok"), out
    assert "symbols=" in out


def test_code_init_rejects_a_missing_directory(tmp_path):
    out = _code_init()(str(tmp_path / "nope"))
    assert out.startswith("Directory not found"), out


def test_subprocess_build_leaves_no_wal(tmp_path):
    """The parent must not be holding a connection while the build runs."""
    (tmp_path / "lib.py").write_text("def a():\n    return 1\n")
    _index_in_subprocess(str(tmp_path), 1)
    from indexer.indexer import CODE_DB_FILENAME

    assert (tmp_path / CODE_DB_FILENAME).exists()
    assert not list(tmp_path.glob(CODE_DB_FILENAME + "-wal"))
