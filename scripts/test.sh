#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# test.sh — RCH single-preset CTest wrapper.
#
# Algorithm: resolve Python, configure/build/test one CMake preset, write a
# JSON status log, and return the aggregate configure/build/test exit status.
# -----------------------------------------------------------------------------
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <preset>" >&2
  exit 64
fi
PRESET="$1"
if [[ ! "$PRESET" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "invalid preset name: $PRESET" >&2
  exit 64
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$ROOT/experiments/logs"
mkdir -p "$LOGDIR"
BUILD_ROOT="${RCH_BUILD_ROOT:-build}"
if [[ "$BUILD_ROOT" = /* ]]; then
  BUILD_BASE="$BUILD_ROOT"
else
  BUILD_BASE="$ROOT/$BUILD_ROOT"
fi
BUILD_DIR="$BUILD_BASE/$PRESET"
FETCHCONTENT_BASE_DIR="$BUILD_BASE/_deps"

parallel_jobs() {
  nproc 2>/dev/null || getconf _NPROCESSORS_ONLN || echo 1
}

JOBS="$(parallel_jobs)"
if [[ -z "${PYTHON:-}" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
PYTHON_EXECUTABLE="$("${PYTHON}" -c 'import sys; print(sys.executable)' 2>/dev/null ||
  command -v "${PYTHON}" 2>/dev/null ||
  printf '%s\n' "${PYTHON}")"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_json="$LOGDIR/test_${PRESET}_${ts}.json"

cd "$ROOT"

cfg_status=0
build_status=0
test_status=0

cmake --preset "$PRESET" -B "$BUILD_DIR" \
  -DPython3_EXECUTABLE:FILEPATH="$PYTHON_EXECUTABLE" \
  -DFETCHCONTENT_BASE_DIR:PATH="$FETCHCONTENT_BASE_DIR" || cfg_status=$?
if [ "$cfg_status" -eq 0 ]; then
  cmake --build "$BUILD_DIR" --parallel "$JOBS" || build_status=$?
fi
if [ "$cfg_status" -eq 0 ] && [ "$build_status" -eq 0 ]; then
  ctest_args=(--test-dir "$BUILD_DIR" --parallel "$JOBS" --output-on-failure)
  if [[ -n "${CTEST_EXCLUDE_REGEX:-}" ]]; then
    ctest_args+=(-E "$CTEST_EXCLUDE_REGEX")
  fi
  ctest "${ctest_args[@]}" || test_status=$?
fi

cat >"$log_json" <<EOF
{
  "preset": "$PRESET",
  "timestamp_utc": "$ts",
  "configure_exit": $cfg_status,
  "build_exit": $build_status,
  "ctest_exit": $test_status
}
EOF

echo "wrote $log_json"

overall=$((cfg_status | build_status | test_status))
exit "$overall"
