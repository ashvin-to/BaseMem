---
name: debug-issue
description: "Diagnose runtime errors, exceptions, and failing tests. Triggers on: debug issue, fix bug, analyze traceback, exception error, investigate failure, test breaking."
---

# Systematic Debugging Protocol

Isolate root causes using symbol search and targeted window reads before writing any code fixes.

## Workflow

| Step | Tool | Input | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `code_find` | `query="ErrorString"`, `grep=True` | Locate exact line numbers of error strings or symbols (~0 tokens) |
| 2 | `get_review_context` | `files=["failing_file.py"]` | Find callers, dependents, and impact radius of the failing module |
| 3 | `code_read` | `path`, `offset`, `limit` (max 50 lines) | Inspect code surrounding the error site |
| 4 | `logInteraction` | `topic`, `decision="Fixed root cause..."` | Log the verified root cause and fix |

## Rules

1. **No Superficial Patches**: Never swallow exceptions or comment out tests.
2. **Empirical Verification**: Inspect actual tracebacks before making code edits.
3. **Log Resolution**: Record why the underlying contract broke using `logInteraction`.
