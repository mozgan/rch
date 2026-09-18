#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# coverage.sh — CMake/CTest coverage orchestrator.
#
# Algorithm: configure/build the coverage preset, run CTest, then merge LLVM
# profraw files with llvm-profdata/llvm-cov or fall back to gcovr for GCC data.
# -----------------------------------------------------------------------------
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmake_bin="${CMAKE:-/usr/bin/cmake}"
ctest_bin="${CTEST:-/usr/bin/ctest}"
preset="${COVERAGE_PRESET:-coverage}"
jobs="${JOBS:-$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN || echo 1)}"
build_root="${RCH_BUILD_ROOT:-build}"
if [[ "${build_root}" = /* ]]; then
  build_base="${build_root}"
else
  build_base="${repo_root}/${build_root}"
fi
build_dir="${build_base}/${preset}"
fetchcontent_base_dir="${build_base}/_deps"
profile_dir="${build_dir}/coverage-profraw"
report_dir="${build_dir}/coverage-report"
if [[ -z "${PYTHON:-}" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
python_executable="$("${PYTHON}" -c 'import sys; print(sys.executable)' 2>/dev/null ||
  command -v "${PYTHON}" 2>/dev/null ||
  printf '%s\n' "${PYTHON}")"

print_coverage_summary() {
  local report_path="$1"
  if [[ ! -s "${report_path}" ]]; then
    echo "[coverage] Coverage report is empty or missing: ${report_path}" >&2
    return
  fi

  echo
  echo "[coverage] Summary from ${report_path}"
  if awk '
    /^TOTAL[[:space:]]/ && NF >= 13 && $4 ~ /%$/ && $7 ~ /%$/ && $10 ~ /%$/ {
      found = 1
    }
    END { exit !found }
  ' "${report_path}"; then
    awk '
      /^TOTAL[[:space:]]/ && NF >= 13 {
        printf("[coverage] TOTAL regions: %s/%s covered (%s)\n", $2 - $3, $2, $4)
        printf("[coverage] TOTAL functions: %s/%s executed (%s)\n", $5 - $6, $5, $7)
        printf("[coverage] TOTAL lines: %s/%s covered (%s)\n", $8 - $9, $8, $10)
        printf("[coverage] TOTAL branches: %s/%s covered (%s)\n", $11 - $12, $11, $13)
      }
    ' "${report_path}"
    echo "[coverage] Lowest line coverage entries:"
    awk '
      NR > 1 && $1 != "Filename" && $1 != "TOTAL" && $10 ~ /%$/ {
        coverage = $10
        sub(/%$/, "", coverage)
        printf("%8.2f%%  %s\n", coverage + 0.0, $1)
      }
    ' "${report_path}" | sort -n | head -10 | sed 's/^/[coverage] /'
  else
    sed -n '1,80p' "${report_path}" | sed 's/^/[coverage] /'
  fi
  echo
}

mkdir -p "${profile_dir}" "${report_dir}"

"${cmake_bin}" --preset "${preset}" -B "${build_dir}" \
  -DPython3_EXECUTABLE:FILEPATH="${python_executable}" \
  -DFETCHCONTENT_BASE_DIR:PATH="${fetchcontent_base_dir}"
"${cmake_bin}" --build "${build_dir}" --parallel "${jobs}"

export LLVM_PROFILE_FILE="${profile_dir}/rch-%p-%m.profraw"
ctest_args=(--test-dir "${build_dir}" --parallel "${jobs}" --output-on-failure)
if [[ -n "${CTEST_EXCLUDE_REGEX:-}" ]]; then
  ctest_args+=(-E "${CTEST_EXCLUDE_REGEX}")
fi
"${ctest_bin}" "${ctest_args[@]}"

shopt -s nullglob
profraw_files=("${profile_dir}"/*.profraw)
llvm_profdata="${LLVM_PROFDATA:-$(command -v llvm-profdata || command -v llvm-profdata-20 || true)}"
llvm_cov="${LLVM_COV:-$(command -v llvm-cov || command -v llvm-cov-20 || true)}"
if ((${#profraw_files[@]} > 0)); then
  if [[ -z "${llvm_profdata}" || -z "${llvm_cov}" ]]; then
    echo "[coverage] ${#profraw_files[@]} LLVM profile files exist under ${profile_dir}, but llvm-profdata/llvm-cov was not found." >&2
    exit 0
  fi
  merged_profile="${report_dir}/coverage.profdata"
  "${llvm_profdata}" merge -sparse "${profraw_files[@]}" -o "${merged_profile}"

  mapfile -t objects < <(
    find "${build_dir}/tests" "${build_dir}/src/cli" \
      -type f -perm -111 \
      ! -name '*.so' ! -name '*.dylib' ! -name '*.dll' \
      2>/dev/null | sort
  )
  if ((${#objects[@]} > 0)); then
    first_object="${objects[0]}"
    object_args=()
    for object in "${objects[@]:1}"; do
      object_args+=("-object" "${object}")
    done
    "${llvm_cov}" report "${first_object}" "${object_args[@]}" \
      -instr-profile="${merged_profile}" \
      -ignore-filename-regex='(/_deps/|/[^/]*build/|/tests/)' \
      >"${report_dir}/coverage.txt"
    echo "[coverage] Wrote ${report_dir}/coverage.txt"
    print_coverage_summary "${report_dir}/coverage.txt"
  else
    echo "[coverage] No executable test/CLI objects found under ${build_dir}" >&2
  fi
elif find "${build_dir}" -name '*.gcda' -print -quit | grep -q .; then
  if command -v gcovr >/dev/null 2>&1; then
    gcovr --root "${repo_root}" --txt "${report_dir}/coverage.txt"
    echo "[coverage] Wrote ${report_dir}/coverage.txt"
    print_coverage_summary "${report_dir}/coverage.txt"
  else
    echo "[coverage] GCC .gcda files exist, but gcovr is not installed; raw data left under ${build_dir}" >&2
  fi
else
  echo "[coverage] Tests passed, but no coverage profile files were found." >&2
fi
