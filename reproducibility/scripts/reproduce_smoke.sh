#!/usr/bin/env bash
# reproducibility/scripts/reproduce_smoke.sh - ordering smoke check.
#
# Algorithm:
#   - Build the reproducibility preset with deterministic compiler flags.
#   - Run the hash-locked CTest regression suite.
#   - Generate three tiny inputs: ASCII PLY, \(10^3\) grid XYZ, and coplanar XYZ.
#   - Run every ordering twice per input and compare `rank,raw_index,key` CSV.
#   - Parse each JSON manifest and require equal output hashes across repeats.
#
# References:
#   National Institute of Standards and Technology, Secure Hash Standard
#   (SHS), 2015, DOI: 10.6028/NIST.FIPS.180-4.
#   Rundgren, Jordan and Erdtman, JSON Canonicalization Scheme (JCS), 2020,
#   DOI: 10.17487/RFC8785.
#   ISO/IEC, Programming Languages - C++, 2020.
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_ROOT="${RCH_BUILD_ROOT:-build}"
if [[ "$BUILD_ROOT" = /* ]]; then
  BUILD_BASE="$BUILD_ROOT"
else
  BUILD_BASE="$ROOT/$BUILD_ROOT"
fi
BUILD_DIR="$BUILD_BASE/repro"
FETCHCONTENT_BASE_DIR="$BUILD_BASE/_deps"
cd "$ROOT"

parallel_jobs() {
  nproc 2>/dev/null || getconf _NPROCESSORS_ONLN || echo 1
}

JOBS="$(parallel_jobs)"
CXX_COMPILER="${CXX:-clang++}"
if [[ -z "${PYTHON:-}" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
PYTHON_EXECUTABLE="$("${PYTHON}" -c 'import sys; print(sys.executable)' 2>/dev/null ||
  command -v "${PYTHON}" 2>/dev/null ||
  printf '%s\n' "${PYTHON}")"

cmake --preset repro -DRCH_BUILD_TOOLS=ON \
  -B "$BUILD_DIR" \
  -DPython3_EXECUTABLE:FILEPATH="$PYTHON_EXECUTABLE" \
  -DFETCHCONTENT_BASE_DIR:PATH="$FETCHCONTENT_BASE_DIR" \
  -DCMAKE_CXX_COMPILER="$CXX_COMPILER"
cmake --build "$BUILD_DIR" --parallel "$JOBS"
ctest_args=(--test-dir "$BUILD_DIR" --parallel "$JOBS" --output-on-failure)
if [[ -n "${CTEST_EXCLUDE_REGEX:-}" ]]; then
  ctest_args+=(-E "${CTEST_EXCLUDE_REGEX}")
fi
ctest "${ctest_args[@]}"

ORDER="${RCH_ORDER_BIN:-$BUILD_DIR/src/cli/rch_order}"
COMPARE="${RCH_COMPARE_BIN:-$BUILD_DIR/src/cli/rch_compare_orders}"
WORK_DIR="${RCH_SMOKE_DIR:-$(mktemp -d)}"

if [[ -z "${RCH_SMOKE_DIR:-}" ]]; then
  trap 'rm -rf "$WORK_DIR"' EXIT
fi

for tool in "$ORDER" "$COMPARE"; do
  if [[ ! -x "$tool" ]]; then
    printf 'required executable is missing or not executable: %s\n' "$tool" >&2
    exit 1
  fi
done

mkdir -p "$WORK_DIR/out"

expected_point_count() {
  case "$1" in
    bunny.ply)
      printf '12\n'
      ;;
    synthetic_10x10x10.xyz)
      printf '1000\n'
      ;;
    coplanar.xyz)
      printf '64\n'
      ;;
    *)
      printf 'unknown smoke input: %s\n' "$1" >&2
      return 1
      ;;
  esac
}

validate_manifest() {
  local manifest_path="$1"
  local expected_method="$2"
  local expected_count="$3"
  "$PYTHON" - "$manifest_path" "$expected_method" "$expected_count" <<'PY'
import json
import re
import sys

path = sys.argv[1]
expected_method = sys.argv[2]
expected_count = int(sys.argv[3])
with open(path, "r", encoding="utf-8") as handle:
    manifest = json.load(handle)

def is_json_int(value):
    return type(value) is int

if manifest.get("status") != "ok":
    raise SystemExit(f"{path}: status is not ok")
if manifest.get("method") != expected_method:
    raise SystemExit(f"{path}: method mismatch")
if not is_json_int(manifest.get("point_count")) or manifest["point_count"] != expected_count:
    raise SystemExit(f"{path}: point_count mismatch")
if not isinstance(manifest.get("robust_fallback_used"), bool):
    raise SystemExit(f"{path}: robust_fallback_used is not boolean")
bits_axis = manifest.get("bits_axis")
if not isinstance(bits_axis, list) or len(bits_axis) != 3:
    raise SystemExit(f"{path}: bits_axis must have three entries")
if not all(is_json_int(value) and 0 <= value <= 63 for value in bits_axis):
    raise SystemExit(f"{path}: invalid bits_axis value")
hash_value = manifest.get("hash")
if not isinstance(hash_value, str) or re.fullmatch(r"[0-9a-f]{64}", hash_value) is None:
    raise SystemExit(f"{path}: hash is not a SHA-256 hex digest")
PY
}

manifest_hash() {
  local manifest_path="$1"
  "$PYTHON" - "$manifest_path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    print(json.load(handle)["hash"])
PY
}

compare_manifest_hashes() {
  local left="$1"
  local right="$2"
  local left_hash
  local right_hash
  left_hash="$(manifest_hash "$left")"
  right_hash="$(manifest_hash "$right")"
  if [[ "$left_hash" != "$right_hash" ]]; then
    printf 'manifest hashes differ: %s != %s\n' "$left" "$right" >&2
    return 1
  fi
}

cat >"$WORK_DIR/bunny.ply" <<'PLY'
ply
format ascii 1.0
comment F6 synthetic smoke surrogate; not the Stanford Bunny dataset.
element vertex 12
property float x
property float y
property float z
end_header
0.00 0.00 0.00
0.12 0.02 0.10
0.18 0.08 0.16
0.24 0.05 0.22
0.30 0.11 0.28
0.36 0.18 0.30
0.40 0.26 0.24
0.34 0.32 0.18
0.26 0.36 0.12
0.18 0.34 0.08
0.10 0.28 0.04
0.04 0.18 0.02
PLY

: >"$WORK_DIR/synthetic_10x10x10.xyz"
for x in {0..9}; do
  for y in {0..9}; do
    for z in {0..9}; do
      printf '%d %d %d\n' "$x" "$y" "$z" >>"$WORK_DIR/synthetic_10x10x10.xyz"
    done
  done
done

: >"$WORK_DIR/coplanar.xyz"
for x in {0..7}; do
  for y in {0..7}; do
    printf '%d %d 0\n' "$x" "$y" >>"$WORK_DIR/coplanar.xyz"
  done
done

methods=(
  input
  lexicographic
  morton
  isotropic_hilbert
  compact_hilbert_aabb
  pca_compact_hilbert
  robust_frame_morton
  rch
)
inputs=(
  bunny.ply
  synthetic_10x10x10.xyz
  coplanar.xyz
)

for input_name in "${inputs[@]}"; do
  input_path="$WORK_DIR/$input_name"
  expected_count="$(expected_point_count "$input_name")"
  stem="${input_name%.*}"
  for method in "${methods[@]}"; do
    csv="$WORK_DIR/out/${stem}_${method}.csv"
    manifest="$WORK_DIR/out/${stem}_${method}.manifest.json"
    csv_repeat="$WORK_DIR/out/${stem}_${method}.repeat.csv"
    manifest_repeat="$WORK_DIR/out/${stem}_${method}.repeat.manifest.json"

    "$ORDER" --input "$input_path" --method "$method" --output "$csv" --manifest "$manifest"
    "$ORDER" --input "$input_path" --method "$method" --output "$csv_repeat" --manifest "$manifest_repeat"
    validate_manifest "$manifest" "$method" "$expected_count"
    validate_manifest "$manifest_repeat" "$method" "$expected_count"
    compare_manifest_hashes "$manifest" "$manifest_repeat"
    "$COMPARE" "$csv" "$csv_repeat" >/dev/null
  done
done

for input_name in "${inputs[@]}"; do
  input_path="$WORK_DIR/$input_name"
  expected_count="$(expected_point_count "$input_name")"
  stem="${input_name%.*}"
  for method in compact_hilbert_aabb pca_compact_hilbert rch; do
    csv="$WORK_DIR/out/${stem}_${method}_monotone_half.csv"
    manifest="$WORK_DIR/out/${stem}_${method}_monotone_half.manifest.json"
    csv_repeat="$WORK_DIR/out/${stem}_${method}_monotone_half.repeat.csv"
    manifest_repeat="$WORK_DIR/out/${stem}_${method}_monotone_half.repeat.manifest.json"

    "$ORDER" --input "$input_path" --method "$method" --bit-allocator monotone_half \
      --output "$csv" --manifest "$manifest"
    "$ORDER" --input "$input_path" --method "$method" --bit-allocator monotone_half \
      --output "$csv_repeat" --manifest "$manifest_repeat"
    validate_manifest "$manifest" "$method" "$expected_count"
    validate_manifest "$manifest_repeat" "$method" "$expected_count"
    compare_manifest_hashes "$manifest" "$manifest_repeat"
    "$COMPARE" "$csv" "$csv_repeat" >/dev/null
  done
done

echo "F6 smoke PASS (preset=repro, work_dir=$WORK_DIR)"
