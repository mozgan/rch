# cmake/Sanitizers.cmake — RCH (Robust Compact Hilbert)
#
# References:
#   - Clang AddressSanitizer: https://clang.llvm.org/docs/AddressSanitizer.html
#   - Clang UndefinedBehaviorSanitizer: https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html
#   - Clang ThreadSanitizer: https://clang.llvm.org/docs/ThreadSanitizer.html
#   - GCC -fsanitize: https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html

include_guard(GLOBAL)

option(RCH_ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(RCH_ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer" OFF)
option(RCH_ENABLE_TSAN "Enable ThreadSanitizer" OFF)

add_library(rch_sanitizers INTERFACE)

if(RCH_ENABLE_ASAN AND RCH_ENABLE_TSAN)
    message(FATAL_ERROR "RCH: ASan and TSan cannot be enabled simultaneously")
endif()

set(_rch_san_flags "")
if(RCH_ENABLE_ASAN)
    list(APPEND _rch_san_flags -fsanitize=address -fno-omit-frame-pointer)
endif()
if(RCH_ENABLE_UBSAN)
    list(
        APPEND _rch_san_flags
        -fsanitize=undefined
        -fno-sanitize-recover=undefined
        -fno-omit-frame-pointer
    )
endif()
if(RCH_ENABLE_TSAN)
    list(APPEND _rch_san_flags -fsanitize=thread -fno-omit-frame-pointer)
endif()

list(REMOVE_DUPLICATES _rch_san_flags)

if(_rch_san_flags)
    target_compile_options(rch_sanitizers INTERFACE ${_rch_san_flags} -g -O1)
    target_link_options(rch_sanitizers INTERFACE ${_rch_san_flags})
    message(STATUS "RCH: Sanitizers enabled: ${_rch_san_flags}")
endif()
