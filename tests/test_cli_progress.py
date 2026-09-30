"""CLI progress display.

`code init` used to draw a progress bar of `length=1` that was updated once,
after the work had already finished, so it showed 0% and then 100% with nothing
in between. The indexer has always reported progress through `progress_cb`; the
CLI simply never passed one.

These tests pin the wiring rather than the pixels: that a callback reaches the
indexer, that it resizes the bar once the real file count is known, and that it
advances by the delta so a repeated or skipped callback cannot desynchronise it.
"""

import pytest
from click.testing import CliRunner


@pytest.fixture
def tiny_project(tmp_path):
    (tmp_path / "a.py").write_bytes(b"def alpha():\n    return 1\n")
    (tmp_path / "b.py").write_bytes(b"def beta():\n    return alpha()\n")
    return tmp_path


def _init(tmp_path, *args):
    from cli.code import code

    return CliRunner().invoke(code, ["init", str(tmp_path), *args])


def test_reports_a_final_summary(tiny_project):
    result = _init(tiny_project)
    assert result.exit_code == 0, result.output
    assert "files" in result.output
    assert "symbols" in result.output
    assert str(tiny_project / ".basemem.code.db") in result.output


def test_does_not_dump_the_indexer_log(tiny_project):
    """The indexer logs an INFO line per phase; it duplicated the summary."""
    result = _init(tiny_project)
    assert "basemem.indexer" not in result.output
    assert "INFO -" not in result.output


def test_verbose_restores_the_indexer_log(tiny_project, monkeypatch):
    """Asserts the level this command sets, not the rendered log.

    Whether the records actually appear depends on a root handler being
    configured, which is cli/main.py's job, not this command's.
    """
    import logging

    seen = []
    monkeypatch.setattr(
        "indexer.indexer.CodeIndexer.index_project",
        lambda self, **kw: (seen.append(logging.getLogger("basemem.indexer").level),
                            {"files": 1, "symbols": 1, "edges": 1, "elapsed": 0.1})[1],
    )
    _init(tiny_project, "--verbose")
    assert seen and seen[-1] == logging.INFO, f"verbose left the level at {seen}"

    seen.clear()
    _init(tiny_project)
    assert seen and seen[-1] == logging.WARNING, f"quiet left the level at {seen}"


def test_quiet_suppresses_the_bar_but_still_reports_the_db(tiny_project):
    result = _init(tiny_project, "--quiet")
    assert result.exit_code == 0, result.output
    assert "files" not in result.output
    assert str(tiny_project / ".basemem.code.db") in result.output


def test_rejects_a_missing_directory(tmp_path):
    result = _init(tmp_path / "nope")
    assert "not a directory" in result.output


def test_progress_callback_advances_by_delta(tiny_project):
    """Regression: advancing by `1 - bar.pos` froze the bar after one step.

    `pos` reaches 1 on the first update, so every later call passed 0 and the
    bar never moved again.
    """
    from indexer.indexer import CodeIndexer

    indexer = CodeIndexer(str(tiny_project))
    try:
        seen = []
        indexer.index_project(
            _max_workers=1,
            progress_cb=lambda phase, done, total: seen.append((phase, done, total)),
        )
    finally:
        indexer.close()

    phases = [p for p, _, _ in seen]
    assert "scan" in phases and "indexing" in phases

    # Every indexing step must be strictly increasing, or the bar desynchronises.
    steps = [done for phase, done, _ in seen if phase == "indexing"]
    assert steps == sorted(steps), f"steps went backwards: {steps}"
    assert len(set(steps)) == len(steps), f"repeated step: {steps}"
    assert steps[-1] == seen[0][2], "final step should equal the discovered total"
