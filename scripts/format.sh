#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# format.sh — clang-format -i over tracked C++ sources.
#
# Algorithm: enumerate tracked include/src C++ files, fall back to `find` when
# git metadata is unavailable, and apply clang-format in place.
# -----------------------------------------------------------------------------
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mapfile -t cxx_files < <(git ls-files 'include/**/*.cpp' 'include/**/*.hpp' 'src/**/*.cpp' 'src/**/*.hpp' 2>/dev/null || true)
if [ "${#cxx_files[@]}" -eq 0 ]; then
  mapfile -t cxx_files < <(find include src -type f \( -name '*.cpp' -o -name '*.hpp' \) | sort)
fi

[ "${#cxx_files[@]}" -gt 0 ] || {
  echo "no C++ files tracked"
  exit 0
}
clang-format -i "${cxx_files[@]}"
