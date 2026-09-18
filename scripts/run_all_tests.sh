#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_all_tests.sh — RCH multi-preset orchestrator.
#
# Algorithm: iterate preset names, invoke scripts/test.sh for each, keep going
# after failures, and return non-zero iff any preset failed.
# -----------------------------------------------------------------------------
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRESETS=(
  debug
  release
  release-clang
  release-gcc
  asan
  ubsan
  fuzz
  tsan
  ci-clang
  ci-gcc
  repro
  bench
  coverage
)
: "${CTEST_EXCLUDE_REGEX:=paper_artifacts_python}"
export CTEST_EXCLUDE_REGEX

if [ "$#" -gt 0 ]; then
  PRESETS=("$@")
fi

results=()
overall=0
for p in "${PRESETS[@]}"; do
  echo "=== preset: $p ==="
  if "$ROOT/scripts/test.sh" "$p"; then
    results+=("$p:PASS")
  else
    rc=$?
    results+=("$p:FAIL($rc)")
    overall=1
  fi
done

echo
echo "=== run_all_tests summary ==="
printf '%s\n' "${results[@]}"
exit "$overall"
