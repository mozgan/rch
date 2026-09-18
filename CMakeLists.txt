# RCH (Robust Compact Hilbert) — top-level CMake entry point.
# Modular configuration lives under cmake/.
cmake_minimum_required(VERSION 3.28)

project(
    rch
    VERSION 0.1.0
    DESCRIPTION "Robust Compact Hilbert ordering — paper artifact repository"
    LANGUAGES CXX
)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# ---- Global C++ standard --------------------------------------------------
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "" FORCE)
endif()

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ---- Modules --------------------------------------------------------------
include(Options)
include(CompilerWarnings)
include(Sanitizers)
include(ReproducibleBuild)
include(Dependencies)
include(Coverage)
include(InstallRules)

# ---- Public header-only core library --------------------------------------
add_library(rch_core INTERFACE)
add_library(rch::core ALIAS rch_core)
target_include_directories(
    rch_core
    INTERFACE
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated/include>"
        "$<INSTALL_INTERFACE:include>"
)
target_compile_features(rch_core INTERFACE cxx_std_23)
target_link_libraries(
    rch_core
    INTERFACE rch_repro_fp rch_warnings rch_sanitizers rch_coverage
)
set_target_properties(rch_core PROPERTIES EXPORT_NAME core)

# Configure version header from in-source template -------------------------
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/version.hpp.in"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/include/rch/core/version.hpp"
    @ONLY
)

# ---- Tests ----------------------------------------------------------------
if(RCH_BUILD_TESTS)
    enable_testing()
    rch_provide_gtest()
    add_subdirectory(tests)
endif()

# ---- Benchmarks (placeholder) --------------------------------------------
if(RCH_BUILD_BENCHMARKS)
    rch_provide_benchmark()
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/benchmarks/CMakeLists.txt")
        add_subdirectory(benchmarks)
    endif()
endif()

# ---- Developer CLIs --------------------------------------------------------
if(RCH_BUILD_TOOLS)
    add_subdirectory(src/cli)
endif()

if(RCH_BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

if(RCH_WITH_CGAL)
    add_subdirectory(adapters/cgal)
endif()

rch_install_rules()
