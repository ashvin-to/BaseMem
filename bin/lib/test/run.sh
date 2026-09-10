#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FAIL=0

for test in test-constants test-rules test-rules-phrasing test-settings test-install test_hooks test_code_tools_hooks test_prompt_context; do
  echo "─── $test ───"
  if node "$DIR/$test.js" 2>&1; then
    echo ""
  else
    echo "FAIL: $test" >&2
    FAIL=1
  fi
done

if [ "$FAIL" = "1" ]; then
  echo "─── SOME TESTS FAILED ───" >&2
  exit 1
else
  echo "─── ALL TESTS PASSED ───"
fi
