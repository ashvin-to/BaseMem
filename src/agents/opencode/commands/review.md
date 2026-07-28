---
description: Review changed files with blast radius and test gaps
---
Run a code review on the currently changed files.

First, get the list of changed files:
```
!`git diff --name-only HEAD`
```

Then call:
```
get_review_context(files=["<file1>", "<file2>"], query="$ARGUMENTS")
```

If code_index is not initialized, run `code_init(projectRoot=".")` first.
For files flagged under KEY RISK or TEST GAPS, use `code_read` to inspect the relevant lines.
Log the review decision with `logInteraction`.
