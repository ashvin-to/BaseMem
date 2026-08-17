---
name: code-review
description: "Review pull requests or git changes with blast-radius estimation, test-gap detection, and risk classification. Triggers on: review code, review diff, pull request review, check blast radius, find test gaps."
---

# Code Review Protocol

Use `get_review_context` to analyze changes in one call instead of manually searching for callers and test files.

## Workflow

| Step | Tool | Input | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `get_review_context` | `files=["a.py","b.py"]`, `query="review"` | Discover callers, test gaps, and blast radius |
| 2 | `code_read` | `path`, `offset`, `limit` (max 50 lines) | Read exact code ranges flagged under KEY RISK or TEST GAPS |
| 3 | `logInteraction` | `topic`, `decision="Approved/flagged..."` | Log review outcome & architectural decisions |

## Rules

1. **One-Shot Impact**: One `get_review_context` call replaces manual `code_find` + `code_impact` + `code_trace`.
2. **Focus on Flagged Risks**: Read only the line ranges reported under `KEY RISK` or `TEST GAPS`.
3. **Log Decision**: Always record the review verdict in the planet memory via `logInteraction`.
