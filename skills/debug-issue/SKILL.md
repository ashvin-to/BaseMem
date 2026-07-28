---
name: debug-issue
description: Diagnose errors — locate, inspect blast radius, read source, log fix
tools: [code_find, get_review_context, code_read, logInteraction]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `code_find` | `query="ErrorString"`, `grep=True` |
| 2 | `get_review_context` | `files=["failing_file.py"]` |
| 3 | `code_read` | Lines around error site |
| 4 | `logInteraction` | `topic`, `decision="Fixed root cause..."` |

Always inspect actual tracebacks before patching. Log root cause on resolution.
