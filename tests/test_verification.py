import json
from pathlib import Path

from mcp_server.server import verify_change


def bundle(root, files=None, artifacts=None, command="", timeout=120):
    return json.loads(verify_change(str(root), files or [], command, artifacts, timeout))


def test_verify_change_reports_source_artifact_and_passing_test(tmp_path: Path):
    source = tmp_path / "module.py"
    source.write_text("VALUE = 1\n")
    artifact = tmp_path / "result.json"
    artifact.write_text('{"value": 1}')

    result = bundle(tmp_path, ["module.py"], ["result.json"], "python -c print(1)")

    assert result["verified"] is True
    assert result["sources"][0]["inspected"] is True
    assert result["sources"][0]["sha256"]
    assert result["artifacts"][0]["summary"] == '{"value":1}'
    assert result["test"]["status"] == "passed"
    assert result["test"]["exit_code"] == 0


def test_verify_change_missing_source_is_unverified(tmp_path: Path):
    result = bundle(tmp_path, ["missing.py"])
    assert result["verified"] is False
    assert result["sources"][0]["exists"] is False
    assert result["unverified"]


def test_verify_change_malformed_arguments_do_not_execute(tmp_path: Path):
    result = bundle(tmp_path, "not-a-list", command="python -c print(1)")
    assert result["test"]["status"] == "invalid_input"
    assert result["test"]["exit_code"] is None
    assert "files must be a list of strings" in result["unverified"]


def test_verify_change_rejects_path_traversal(tmp_path: Path):
    result = bundle(tmp_path, ["../outside.py"], command="python -c print(1)")
    assert result["verified"] is False
    assert any("escapes projectRoot" in item for item in result["unverified"])
    assert result["test"]["status"] == "invalid_input"


def test_verify_change_reports_failed_test(tmp_path: Path):
    result = bundle(tmp_path, command="python -c 'import sys; sys.exit(1)'")
    assert result["test"]["status"] == "failed"
    assert result["test"]["exit_code"] == 1
    assert result["verified"] is False


def test_verify_change_timeout_is_bounded(tmp_path: Path):
    result = bundle(tmp_path, command="python -c 'import time; time.sleep(2)'", timeout=1)
    assert result["test"]["status"] == "error"
    assert result["test"]["duration_ms"] > 0
