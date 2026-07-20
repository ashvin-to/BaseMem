"""Tests for silent native-tool capture (capture_native.py)."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURE_PY = os.path.join(ROOT, 'bin', 'lib', 'capture_native.py')
PYTHON = 'python3'


def run_capture(payload, db_path):
    env = dict(os.environ)
    env['BASEMEM_DB_PATH'] = db_path
    p = subprocess.run(
        [PYTHON, CAPTURE_PY],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    return p


def notes(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute('SELECT kind, content, title FROM notes ORDER BY id')]
    c.close()
    return rows


def test_read_captured():
    db = tempfile.mktemp(suffix='.db')
    run_capture({"tool": "Read", "params": {"file_path": "src/foo.py"}, "agent_id": "opencode"}, db)
    ns = notes(db)
    assert any(n['content'] == 'read src/foo.py' for n in ns), ns
    os.remove(db)


def test_edit_sets_pending_flag():
    db = tempfile.mktemp(suffix='.db')
    run_capture({"tool": "Edit", "params": {"file_path": "src/bar.js"}}, db)
    ns = notes(db)
    assert any(n['content'] == 'edited src/bar.js' for n in ns), ns
    assert any(n['content'] == 'pending_logInteraction' for n in ns), ns
    os.remove(db)


def test_grep_captured():
    db = tempfile.mktemp(suffix='.db')
    run_capture({"tool": "Grep", "params": {"pattern": "hello"}}, db)
    ns = notes(db)
    assert any(n['content'] == 'searched hello' for n in ns), ns
    os.remove(db)


def test_non_native_tool_ignored():
    db = tempfile.mktemp(suffix='.db')
    run_capture({"tool": "code_read", "params": {"filePath": "x"}}, db)
    assert notes(db) == [], "non-native tool should not be captured"
    os.remove(db)


def test_missed_log_flag():
    db = tempfile.mktemp(suffix='.db')
    run_capture({"tool": "__missed_log__", "params": {}}, db)
    ns = notes(db)
    assert any(n['content'] == 'missed_logInteraction' for n in ns), ns
    os.remove(db)


if __name__ == '__main__':
    for name in list(globals()):
        if name.startswith('test_'):
            globals()[name]()
            print('PASS', name)
    print('All capture tests passed')
