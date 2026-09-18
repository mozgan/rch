# cmake/CompilerWarnings.cmake — RCH (Robust Compact Hilbert)
#
#   - GCC warning options: https://gcc.gnu.org/onlinedocs/gcc/Warning-Options.html
#   - Clang diagnostic flags: https://clang.llvm.org/docs/DiagnosticsReference.html

include_guard(GLOBAL)

option(RCH_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" ON)

add_library(rch_warnings INTERFACE)

include(CheckCXXCompilerFlag)

function(rch_add_supported_warning target flag)
    string(MAKE_C_IDENTIFIER "RCH_HAS_${flag}" _rch_flag_var)
    check_cxx_compiler_flag("${flag}" "${_rch_flag_var}")
    if(${_rch_flag_var})
        target_compile_options("${target}" INTERFACE "${flag}")
    endif()
endfunction()

set(_rch_clang_gcc_common
    -Wall
    -Wextra
    -Wpedantic
    -Wshadow
    -Wnon-virtual-dtor
    -Wdelete-non-virtual-dtor
    -Wctor-dtor-privacy
    -Wcast-align
    -Wunused
    -Woverloaded-virtual
    -Wconversion
    -Wsign-conversion
    -Wnull-dereference
    -Wdouble-promotion
    -Wfloat-equal
    -Wformat=2
    -Wimplicit-fallthrough
    -Wdeprecated-copy
    -Wold-style-cast
    -Wzero-as-null-pointer-constant
    -Wextra-semi
    -Wreorder
    -Wrange-loop-construct
    -Wno-vexing-parse
    -Wsign-promo
    -Wswitch
    -Wswitch-default
    -Wswitch-enum
    -Wundef
    -Wcast-qual
    -Wvla
    -Wchar-subscripts
    -Wshift-negative-value
    -Winit-self
    -Wuninitialized
    -Wpacked
    -Wredundant-decls
)

set(_rch_gcc_extra
    -Wmisleading-indentation
    -Wduplicated-cond
    -Wduplicated-branches
    -Wlogical-op
    -Wuseless-cast
    -Wclass-memaccess
    -Wredundant-tags
    -Wstrict-null-sentinel
    -Wsized-deallocation
    -Wcomma-subscript
    -Wplacement-new=2
    -Wzero-length-bounds
    -Wnoexcept
    -Wsuggest-final-types
    -Wsuggest-final-methods
    -Wunsafe-loop-optimizations
    -Wno-aggressive-loop-optimizations
)

set(_rch_clang_extra
    -Wshadow-all
    -Wmost
    -Winvalid-constexpr
    -Winfinite-recursion
)

if(
    CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
    OR CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang"
)
    target_compile_options(rch_warnings INTERFACE ${_rch_clang_gcc_common})
    foreach(_rch_warning IN LISTS _rch_clang_extra)
        rch_add_supported_warning(rch_warnings "${_rch_warning}")
    endforeach()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(
        rch_warnings
        INTERFACE ${_rch_clang_gcc_common} ${_rch_gcc_extra}
    )
else()
    message(
        WARNING
        "RCH: Unsupported compiler '${CMAKE_CXX_COMPILER_ID}' — warning policy not applied"
    )
endif()

foreach(
    _rch_warning
    -Wsuggest-override
    -Wnoexcept-type
    -Wmismatched-new-delete
    -Wmismatched-tags
    -Wdangling-reference
    -fdiagnostics-parseable-fixits
    -fdiagnostics-color=always
    -fconcepts
    -fconstexpr-depth=256
    -ftemplate-depth=256
    -fstrict-enums
    -fsized-deallocation
    -frtti
)
    rch_add_supported_warning(rch_warnings "${_rch_warning}")
endforeach()
