---
name: review
description: Review changed files with blast radius and test gaps
---

Review the currently changed files.

Get changed files:
```
!`git diff --name-only HEAD`
```

Then:
```
get_review_context(files=["<file1>", "<file2>"], query="review changes")
```

If code graph not initialized, run `code_init(projectRoot=".")` first.
Inspect KEY RISK and TEST GAP files with `code_read`.
