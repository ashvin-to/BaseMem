"""Tests for the CLI interface (cli/main.py)"""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


class TestCLI:
    def test_cli_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "BaseMem" in result.output

    def test_list_planets_empty(self, runner, temp_db_path):
        import sqlite3

        from storage.sessions import _ensure_schema
        conn = sqlite3.connect(temp_db_path)
        _ensure_schema(conn)
        conn.close()
        result = runner.invoke(cli, ["--db", temp_db_path, "list-planets"])
        assert result.exit_code == 0
        assert "No planets" in result.output

    def test_list_planets(self, runner, temp_db_path):
        import sqlite3
        conn = sqlite3.connect(temp_db_path)
        from storage.sessions import _ensure_schema
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO planets (topic, display_topic, status, goal, current_state) VALUES (?, ?, ?, ?, ?)",
            ("test", "Test Planet", "active", "a goal", "a state"),
        )
        conn.commit()
        conn.close()

        result = runner.invoke(cli, ["--db", temp_db_path, "list-planets"])
        assert result.exit_code == 0
        assert "Test Planet" in result.output
        assert "a goal" in result.output
        assert "a state" in result.output

    def test_search(self, runner, temp_db_path):
        import sqlite3
        conn = sqlite3.connect(temp_db_path)
        from storage.sessions import _ensure_schema
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO planets (topic, display_topic, status) VALUES (?, ?, ?)",
            ("findme", "Find Me", "active"),
        )
        conn.commit()
        conn.close()

        result = runner.invoke(cli, ["--db", temp_db_path, "search", "Find"])
        assert result.exit_code == 0
        assert "Find Me" in result.output

    def test_search_no_results(self, runner, temp_db_path):
        import sqlite3

        from storage.sessions import _ensure_schema
        conn = sqlite3.connect(temp_db_path)
        _ensure_schema(conn)
        conn.close()
        result = runner.invoke(cli, ["--db", temp_db_path, "search", "nonexistent"])
        assert result.exit_code == 0
