---
name: debug-issue
description: Investigate errors, check dependencies, read source lines, and record root cause fix
tools: [code_find, get_review_context, code_read, logInteraction]
---

## When to use this skill
Use this skill when diagnosing a runtime bug, failing test case, or unhandled exception traceback.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `code_find(error_message, grep=True)` | `query="KeyError"`, `grep=True` | File and line location of error site |
| 2 | `get_review_context(files)` | `files=["failing_file.py"]` | Blast radius and callers of target module |
| 3 | `code_read(filePath, offset, limit)` | `filePath`, line range | Source code surrounding error site |
| 4 | `logInteraction(topic, decision=...)` | `topic="repo-name"`, `decision="Fixed root cause..."` | Persisted fix explanation on planet |

## Example

```python
# Step 1: Grep codebase for error string or function name
code_find("Invalid node ID", grep=True)

# Step 2: Get review context for affected file
get_review_context(files=["storage/sessions.py"])

# Step 3: Read lines around error handler
code_read(filePath="storage/sessions.py", offset=850, limit=25)

# Step 4: Log fix decision
logInteraction(topic="basemem", decision="Handled invalid node ID gracefully by returning early error message.")
```

## Notes
Never attempt to guess or patch bugs without inspecting actual log tracebacks. Always trace upstream caller inputs using `get_review_context` or `code_read` before applying a fix. Log the root cause upon resolution.
