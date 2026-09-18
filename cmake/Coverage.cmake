# cmake/Coverage.cmake - opt-in coverage instrumentation.

include_guard(GLOBAL)

option(RCH_ENABLE_COVERAGE "Enable coverage instrumentation" OFF)

add_library(rch_coverage INTERFACE)

if(RCH_ENABLE_COVERAGE)
    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        target_compile_options(rch_coverage INTERFACE --coverage -O0 -g)
        target_link_options(rch_coverage INTERFACE --coverage)
    elseif(
        CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
        OR CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang"
    )
        target_compile_options(
            rch_coverage
            INTERFACE -fprofile-instr-generate -fcoverage-mapping -O0 -g
        )
        target_link_options(rch_coverage INTERFACE -fprofile-instr-generate)
    else()
        message(
            FATAL_ERROR
            "RCH: coverage is unsupported for ${CMAKE_CXX_COMPILER_ID}"
        )
    endif()
endif()
