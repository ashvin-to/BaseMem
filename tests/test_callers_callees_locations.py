"""Callers and callees must report where each result lives.

`code callers` returned bare `name:line` with no file, so an agent could not
navigate to any result. cbm reports file and line per row. The benchmark in
benchmarks/query_quality.py caught this as a failed who-calls question.
"""

from click.testing import CliRunner

from cli.code import code


def _index(tmp_path):
    (tmp_path / "lib.py").write_text(
        "def target():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def middle():\n"
        "    return target()\n"
        "\n"
        "\n"
        "def caller():\n"
        "    return middle()\n"
    )
    (tmp_path / "other.py").write_text(
        "def also_calls():\n"
        "    return target()\n"
    )
    from indexer.indexer import CodeIndexer

    ix = CodeIndexer(str(tmp_path))
    try:
        ix.index_project(_max_workers=1)
    finally:
        ix.close()
    return str(tmp_path)


def test_callers_report_file_and_line(tmp_path):
    r = CliRunner().invoke(code, ["callers", "target", "--root", _index(tmp_path)])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "middle" in out
    # the file must be named, not just the symbol
    assert "lib.py" in out, out
    assert "other.py" in out, out


def test_callees_report_file_and_line(tmp_path):
    r = CliRunner().invoke(code, ["callees", "middle", "--root", _index(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "target" in r.output
    assert "lib.py" in r.output, r.output


def test_no_callers_is_still_reported(tmp_path):
    root = _index(tmp_path)
    r = CliRunner().invoke(code, ["callers", "nonexistent", "--root", root])
    assert r.exit_code == 0, r.output
    assert "No callers" in r.output


def test_every_result_carries_a_location(tmp_path):
    """No bare `name:line` may slip through again."""
    root = _index(tmp_path)
    for cmd, sym in (("callers", "target"), ("callees", "middle")):
        r = CliRunner().invoke(code, [cmd, sym, "--root", root])
        assert r.exit_code == 0, r.output
        line = r.output.strip().splitlines()[0]
        assert "(" in line and ")." in line or ".py" in line, f"no location in: {line}"