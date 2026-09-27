import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "bin" / "lib" / "install.js"


def run_verify(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        ["node", str(INSTALL), "verify", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_verify_json_reports_missing_optional_clients(tmp_path: Path):
    result = run_verify(tmp_path, "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert all(client["name"] != "kilo" for client in payload["clients"])


def test_verify_reports_stale_installed_client(tmp_path: Path):
    client_dir = tmp_path / ".config" / "kilo"
    client_dir.mkdir(parents=True)
    rule_file = client_dir / "basemem.md"
    rule_file.write_text("stale rules")

    result = run_verify(tmp_path, "--json")
    payload = json.loads(result.stdout)
    kilo = next(client for client in payload["clients"] if client["name"] == "kilo")
    assert result.returncode == 1
    assert kilo["status"] == "FAIL"
    assert "verify_change" in kilo["missing"]
