# cmake/Options.cmake — RCH (Robust Compact Hilbert)

include_guard(GLOBAL)

option(RCH_BUILD_TESTS "Build unit/property/regression tests" ON)
option(RCH_BUILD_BENCHMARKS "Build Google-Benchmark micro-benches" OFF)
option(RCH_BUILD_TOOLS "Build developer tools (tools/*)" OFF)
option(RCH_BUILD_EXAMPLES "Build small header-only usage examples" OFF)

# Adapter feature flags
option(RCH_WITH_CGAL "Build CGAL adapter (A7 baseline)" OFF)
option(RCH_WITH_PCL "Build PCL adapter" OFF)
option(RCH_WITH_OPEN3D "Build Open3D adapter" OFF)

# Fuzzing
option(RCH_BUILD_FUZZ "Build libFuzzer harnesses (Clang only)" OFF)

if(
    RCH_BUILD_FUZZ
    AND NOT (
        CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
        OR CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang"
    )
)
    message(
        FATAL_ERROR
        "RCH: RCH_BUILD_FUZZ=ON requires Clang (got ${CMAKE_CXX_COMPILER_ID})"
    )
endif()

message(
    STATUS
    "RCH options: TESTS=${RCH_BUILD_TESTS} BENCH=${RCH_BUILD_BENCHMARKS} "
    "TOOLS=${RCH_BUILD_TOOLS} CGAL=${RCH_WITH_CGAL} PCL=${RCH_WITH_PCL} "
    "OPEN3D=${RCH_WITH_OPEN3D} FUZZ=${RCH_BUILD_FUZZ} "
    "EXAMPLES=${RCH_BUILD_EXAMPLES}"
)
