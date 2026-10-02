#!/usr/bin/env bash
# Run the whole job-agent test suite: Python (unittest) and Node (node --test).
# No third-party test runner is required on purpose — this repo should stay
# runnable on a clean Mac with only python3 and node installed.
set -uo pipefail

cd "$(dirname "$0")/.."

status=0

echo "== Python (unittest) =="
if ! python3 -m unittest discover -s tests -q; then
  status=1
fi

echo
echo "== Node (node --test) =="
if ! node --test "tests/**/*.test.mjs"; then
  status=1
fi

echo
if [ "$status" -eq 0 ]; then
  echo "All job-agent tests passed."
else
  echo "Test failures above." >&2
fi
exit "$status"
