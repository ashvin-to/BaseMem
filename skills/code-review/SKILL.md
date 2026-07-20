---
name: code-review
description: Review changed files using compact blast radius, test gaps, and targeted code reading
tools: [get_review_context, code_read, logInteraction]
---

## When to use this skill
Use this skill when reviewing code changes, pull requests, or diffs across one or more project files. It provides blast radius, entry points, test gaps, and key risks in a single compact call under 300 tokens.

## Workflow

| Step | Tool | Input | What you get |
|------|------|-------|--------------|
| 1 | `get_review_context(files, query)` | `files=["auth/login.py", "auth/session.py"]`, `query="review change"` | Compact pre-digested summary (blast radius, entry points, test gaps, key risks) |
| 2 | `code_read(filePath, offset, limit)` | `filePath` of KEY RISK or TEST GAP files | Target lines for detailed inspection |
| 3 | `logInteraction(topic, ...)` | `topic="repo-name"`, `decision="..."` | Audit finding or review approval logged |

## Example

```python
# Step 1: Fetch review context in one shot
get_review_context(files=["auth/login.py", "auth/session.py"], query="check session security")

# Step 2: Read target file flagged under KEY RISK or TEST GAPS
code_read(filePath="auth/middleware.py", offset=1, limit=50)

# Step 3: Log review decision
logInteraction(topic="basemem", decision="Approved auth changes; flagged test gap in middleware.")
```

## Notes
Do not run `code_find` + `code_impact` + `code_trace` separately for standard review tasks — `get_review_context` replaces all three in a single call. Only use `code_impact` or `code_trace` directly for deep multi-level dependency graphs.
