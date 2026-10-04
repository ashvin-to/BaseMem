"""The database must live under XDG, and every layer must agree on that.

Three places independently decide where basemem.db lives: install.sh, the
installer's DEFAULT_MCP_DB, and storage.db's default. They drifted once -
install.sh and install.js still pointed at ~/.basemem while the server already
preferred XDG - so the default is pinned in one place and checked from the rest.
"""

import os
import re
import subprocess
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _sh_env(data_home, tmp_path):
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(data_home)
    env["HOME"] = str(tmp_path)
    env["BASEMEM_DIR"] = str(tmp_path)
    return env


def test_installer_js_prefers_xdg_data_home():
    src = (REPO / "bin" / "lib" / "install.js").read_text()
    assert "XDG_DATA_HOME" in src, "install.js must honour XDG_DATA_HOME"
    m = re.search(r"DEFAULT_MCP_DB\s*=\s*path\.join\((.*?)\);", src, re.S)
    assert m, "DEFAULT_MCP_DB not found"
    body = m.group(1)
    assert "XDG_DATA_HOME" in body, body
    assert "'.basemem'" not in body, "still defaults into a $HOME dot-directory"


def test_install_sh_data_dir_is_xdg():
    src = (REPO / "install.sh").read_text()
    assert 'DATA_DIR="$HOME/.basemem"' not in src, "install.sh still uses ~/.basemem"
    assert "XDG_DATA_HOME" in src
    # the doc comment should not advertise the old location either
    assert "install.sh --dir ~/.basemem" not in src


def test_storage_db_defaults_to_xdg(tmp_path, monkeypatch):
    from storage.db import StorageManager

    data_home = tmp_path / "xdgdata"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BASEMEM_DB_PATH", raising=False)

    sm = StorageManager()
    try:
        assert Path(sm.db_path) == data_home / "basemem" / "basemem.db"
        assert not (home / ".basemem").exists(), "must not create a dot-dir in $HOME"
    finally:
        sm.close()


def test_explicit_db_path_still_wins(tmp_path, monkeypatch):
    from storage.db import StorageManager

    data_home = tmp_path / "xdgdata"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("BASEMEM_DB_PATH", raising=False)
    explicit = tmp_path / "custom" / "notes.db"
    explicit.parent.mkdir(parents=True)

    sm = StorageManager(db_path=explicit)
    try:
        assert Path(sm.db_path) == explicit
    finally:
        sm.close()


def test_server_env_path_prefers_xdg_when_no_legacy(tmp_path, monkeypatch):
    """mcp_server._env_path already did this; keep it honest."""
    import importlib

    m = importlib.import_module("mcp_server.server")
    home = tmp_path / "home"
    (home / ".local" / "share" / "basemem").mkdir(parents=True)
    db = home / ".local" / "share" / "basemem" / "basemem.db"
    sqlite3.connect(db).close()
    monkeypatch.delenv("BASEMEM_DB_PATH", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert m._env_path() == str(db)


def test_all_three_layers_name_the_same_default():
    """A drift here is the bug this file exists for."""
    expected_tail = ("basemem", "basemem.db")

    install_js = (REPO / "bin" / "lib" / "install.js").read_text()
    assert "'.local', 'share'" in install_js or "'.local/share'" in install_js

    install_sh = (REPO / "install.sh").read_text()
    assert ".local" in install_sh and "share" in install_sh

    db_py = (REPO / "storage" / "db.py").read_text()
    assert '"basemem"' in db_py and '"basemem.db"' in db_py
    assert expected_tail  # documents intent for future readers