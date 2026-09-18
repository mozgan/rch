# cmake/ReproducibleBuild.cmake — RCH (Robust Compact Hilbert)
#
# Determinism:
#   - -ffp-contract=off          : FMA contraction closed in default clang/gcc
#   - -fno-fast-math             : aggressive IEEE-754 violations are disabled
#   - -frounding-math            : rounding mode change assumption is disabled
#   - -fsignaling-nans           : sNaN is preserved (debug-ability + standard compliance)
#   - -fno-associative-math      : (a+b)+c == a+(b+c) transformation is disabled
#
# References:
#   - Goldberg, "What Every Computer Scientist Should Know About FP" 1991 (R_GLD).
#   - GCC Optimize-Options: `-ffp-contract`, `-frounding-math`, `-fsignaling-nans`, `-fno-associative-math`
#   - Clang Users Manual — Controlling Floating Point Behavior: https://clang.llvm.org/docs/UsersManual.html#controlling-floating-point-behavior

include_guard(GLOBAL)

add_library(rch_repro_fp INTERFACE)

if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(
        rch_repro_fp
        INTERFACE
            -ffp-contract=off
            -fno-fast-math
            -frounding-math
            -fsignaling-nans
            -fno-associative-math
    )
elseif(
    CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
    OR CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang"
)
    target_compile_options(
        rch_repro_fp
        INTERFACE -ffp-contract=off -fno-fast-math -ffp-model=strict
    )
else()
    message(
        WARNING
        "RCH: Reproducible-build FP flags unsupported on '${CMAKE_CXX_COMPILER_ID}' — "
        "bit-exact integer-domain claims may not hold"
    )
endif()

target_compile_definitions(rch_repro_fp INTERFACE RCH_REQUIRE_IEC559=1)
