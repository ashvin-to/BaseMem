import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_integration_manifest_matches_installer_configuration():
    manifest = json.loads((ROOT / "bin/lib/integrations.json").read_text())
    raw_agents = subprocess.check_output(
        ["node", "-e", "console.log(JSON.stringify(require('./bin/lib/install.js').AGENTS))"],
        cwd=ROOT,
        text=True,
    )
    agents = json.loads(raw_agents)

    assert [(a["name"], a["tier"], tuple(a["capabilities"])) for a in manifest["integrations"]] == [
        (a["name"], a["tier"], tuple(a["capabilities"])) for a in agents
    ]
    matrix = (ROOT / "doc/integrations.md").read_text()
    for agent in manifest["integrations"]:
        assert agent["display_name"] in matrix


def test_new_inventory_does_not_deploy_writable_task_workflow():
    assert not (ROOT / "skills/task-workflow").exists()
    assert not (ROOT / "src/agents/opencode/commands/tasks.md").exists()

    readme = (ROOT / "README.md").read_text().lower()
    assert "does not replace coding-agent todos" in readme
    assert "task_create" not in readme
    assert "task_update" not in readme
    assert "`/tasks`" not in readme

    inventory = (ROOT / "skills/README.md").read_text().lower()
    assert "not installed by new releases" in inventory


def test_legacy_task_cleanup_remains_in_installer():
    source = (ROOT / "bin/lib/install.js").read_text()
    assert "'tasks.md'" in source
    assert "'task-workflow'" in source
    assert "basememSkills = ['using-basemem', 'code-review', 'explore-codebase', 'debug-issue', 'session-start', 'task-workflow']" in source
