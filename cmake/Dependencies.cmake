# cmake/Dependencies.cmake — RCH (Robust Compact Hilbert)
#
# Resources:
#   - GoogleTest releases:  https://github.com/google/googletest/releases
#   - Google Benchmark:     https://github.com/google/benchmark/releases
#   - simdjson:             https://github.com/simdjson/simdjson/releases
#   - libmorton:            https://github.com/Forceflow/libmorton/releases

include_guard(GLOBAL)

include(FetchContent)
set(FETCHCONTENT_QUIET FALSE)
set(
    FETCHCONTENT_BASE_DIR
    "${CMAKE_SOURCE_DIR}/build/_deps"
    CACHE PATH "Shared FetchContent cache for third-party dependencies"
)

# ---- GoogleTest -----------------------------------------------------------
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
    GIT_SHALLOW TRUE
)

# ---- Google Benchmark -----------------------------------------------------
FetchContent_Declare(
    googlebenchmark
    GIT_REPOSITORY https://github.com/google/benchmark.git
    GIT_TAG v1.8.3
    GIT_SHALLOW TRUE
)

# ---- simdjson -------------------------------------------------------------
FetchContent_Declare(
    simdjson
    GIT_REPOSITORY https://github.com/simdjson/simdjson.git
    GIT_TAG v3.9.4
    GIT_SHALLOW TRUE
)

# ---- libmorton ------------------------------------------------------------
FetchContent_Declare(
    libmorton
    GIT_REPOSITORY https://github.com/Forceflow/libmorton.git
    GIT_TAG v0.2.12
    GIT_SHALLOW TRUE
    SOURCE_SUBDIR rch_no_upstream_cmake
)

# ---- Dispatch -------------------------------------------------------------
function(rch_provide_gtest)
    if(TARGET GTest::gtest_main)
        return()
    endif()
    find_package(GTest CONFIG QUIET)
    if(NOT TARGET GTest::gtest_main)
        find_package(GTest QUIET)
    endif()
    if(TARGET GTest::gtest_main)
        message(STATUS "RCH dependency: using system GoogleTest")
        return()
    endif()
    message(STATUS "RCH dependency: system GoogleTest not found; fetching v1.14.0")
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
    if(TARGET gtest AND NOT TARGET GTest::gtest)
        add_library(GTest::gtest ALIAS gtest)
        add_library(GTest::gtest_main ALIAS gtest_main)
    endif()
endfunction()

function(rch_provide_benchmark)
    if(TARGET benchmark::benchmark AND TARGET benchmark::benchmark_main)
        return()
    endif()
    find_package(benchmark CONFIG QUIET)
    if(TARGET benchmark::benchmark AND TARGET benchmark::benchmark_main)
        message(STATUS "RCH dependency: using system Google Benchmark")
        return()
    endif()
    message(STATUS "RCH dependency: system Google Benchmark not found; fetching v1.8.3")
    set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
    set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
    set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googlebenchmark)
    FetchContent_GetProperties(googlebenchmark)
    if(TARGET benchmark)
        target_include_directories(
            benchmark
            SYSTEM
            PUBLIC "${googlebenchmark_SOURCE_DIR}/include"
        )
    endif()
endfunction()

function(rch_provide_simdjson)
    if(TARGET simdjson::simdjson)
        return()
    endif()
    find_package(simdjson CONFIG QUIET)
    if(TARGET simdjson AND NOT TARGET simdjson::simdjson)
        add_library(simdjson::simdjson ALIAS simdjson)
    endif()
    if(TARGET simdjson::simdjson)
        message(STATUS "RCH dependency: using system simdjson")
        return()
    endif()
    message(STATUS "RCH dependency: system simdjson not found; fetching v3.9.4")
    set(SIMDJSON_DEVELOPER_MODE OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(simdjson)
endfunction()

function(rch_provide_libmorton)
    if(TARGET libmorton::libmorton)
        return()
    endif()
    find_package(libmorton CONFIG QUIET)
    if(TARGET libmorton::libmorton)
        message(STATUS "RCH dependency: using system libmorton")
        return()
    endif()
    find_path(RCH_SYSTEM_LIBMORTON_INCLUDE_DIR NAMES libmorton/morton.h)
    if(RCH_SYSTEM_LIBMORTON_INCLUDE_DIR)
        message(STATUS "RCH dependency: using system libmorton headers")
        add_library(libmorton INTERFACE)
        target_include_directories(
            libmorton SYSTEM INTERFACE "${RCH_SYSTEM_LIBMORTON_INCLUDE_DIR}"
        )
        add_library(libmorton::libmorton ALIAS libmorton)
        return()
    endif()
    message(STATUS "RCH dependency: system libmorton not found; fetching v0.2.12")
    FetchContent_MakeAvailable(libmorton)
    FetchContent_GetProperties(libmorton)
    if(NOT TARGET libmorton)
        add_library(libmorton INTERFACE)
    endif()
    target_include_directories(
        libmorton
        SYSTEM
        INTERFACE "${libmorton_SOURCE_DIR}/include"
    )
    if(NOT TARGET libmorton::libmorton)
        add_library(libmorton::libmorton ALIAS libmorton)
    endif()
endfunction()
