"""Tests for get_review_context, tool consolidation, and skills system."""

import os
import tempfile
import subprocess

from mcp_server.server import get_review_context, session_start, code_init, session_end


def test_get_review_context_uninitialized():
    with tempfile.TemporaryDirectory() as tmpdir:
        res = get_review_context(["foo.py"], projectRoot=tmpdir)
        assert res == "Code graph not initialized. Run code_init(projectRoot) first."


def test_get_review_context_initialized():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create dummy Python files
        auth_file = os.path.join(tmpdir, "auth.py")
        with open(auth_file, "w") as f:
            f.write("def login(): pass\n")
        
        main_file = os.path.join(tmpdir, "main.py")
        with open(main_file, "w") as f:
            f.write("from auth import login\ndef run(): login()\n")
            
        # Index project
        code_init(tmpdir)
        
        # Get review context
        res = get_review_context(["auth.py"], projectRoot=tmpdir)
        assert "CHANGED: auth.py" in res
        assert "BLAST RADIUS" in res or "ENTRY POINTS" in res


def test_session_start_create_and_resume():
    res1 = session_start(topic="test_topic", title="Test Session", agent_id="agent1")
    assert "Session created: id=" in res1
    
    # Extract session ID
    sid_str = res1.split("id=")[1].split(",")[0]
    sid = int(sid_str)

    # Pause session
    session_end(session_id=sid, pause=True)

    # Resume via session_start
    res2 = session_start(topic="test_topic", title="Resume Session", agent_id="agent2", session_id=sid)
    assert f"Session {sid} resumed. Agent: agent2." in res2


def test_skills_installation_node():
    res = subprocess.run(
        ["node", "bin/lib/install.js", "install", "claude"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "skills" in res.stdout
    home = os.path.expanduser("~")
    
    # Verify README.md is copied
    readme_path = os.path.join(home, ".claude", "skills", "using-basemem", "README.md")
    assert os.path.isfile(readme_path)

    # Verify using-basemem/SKILL.md is copied directly
    using_basemem_skill = os.path.join(home, ".claude", "skills", "using-basemem", "SKILL.md")
    assert os.path.isfile(using_basemem_skill)
    content = open(using_basemem_skill).read()
    assert "name: using-basemem" in content
    assert "## Workflow" in content

    for skill in ["code-review", "session-start", "explore-codebase", "debug-issue", "task-workflow"]:
        skill_path = os.path.join(home, ".claude", "skills", "using-basemem", skill, "SKILL.md")
        assert os.path.isfile(skill_path)
        content = open(skill_path).read()
        assert f"name: {skill}" in content
        assert "## Workflow" in content
