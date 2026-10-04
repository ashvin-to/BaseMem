"""Query tools must refuse an oversized implicit index with a usable message."""

import pytest

from indexer.lifecycle import AutoIndexRefused
from mcp_server.server import code_context, code_files


@pytest.fixture
def refuse(monkeypatch):
    def boom(project_root, max_workers=4):
        raise AutoIndexRefused(f"too big: {project_root}")

    import indexer.lifecycle as lc
    monkeypatch.setattr(lc, "open_or_create_index", boom)


def test_code_context_reports_refusal_instead_of_raising(tmp_path, refuse):
    out = code_context("anything", projectRoot=str(tmp_path))
    assert out.startswith("code_context:"), out
    assert "too big" in out


def test_code_files_reports_refusal_instead_of_raising(tmp_path, refuse):
    out = code_files(projectRoot=str(tmp_path))
    assert out.startswith("code_files:"), out
    assert "too big" in out


def test_refusal_names_the_explicit_command(tmp_path, monkeypatch):
    monkeypatch.setattr("indexer.lifecycle.MAX_AUTO_INDEX_FILES", 1)
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")

    out = code_files(projectRoot=str(tmp_path))
    assert "mem code init" in out, out
    assert not (tmp_path / ".basemem.code.db").exists()


def test_normal_project_still_answers(tmp_path):
    (tmp_path / "a.py").write_text("def hello():\n    return 1\n")
    out = code_files(projectRoot=str(tmp_path))
    assert out.startswith("code_files"), out
    assert "a.py" in out