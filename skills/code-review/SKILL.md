---
name: code-review
description: Review changes with compact blast radius, test gaps, and targeted reads
tools: [get_review_context, code_read, logInteraction]
---

## Workflow

| Step | Tool | Input |
|------|------|-------|
| 1 | `get_review_context` | `files=["a.py","b.py"]`, `query="review"` |
| 2 | `code_read` | Files flagged under KEY RISK or TEST GAPS |
| 3 | `logInteraction` | `topic`, `decision="Approved/flagged..."` |

One `get_review_context` call replaces `code_find` + `code_impact` + `code_trace` for standard reviews.
