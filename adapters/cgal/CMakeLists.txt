# CGAL spatial_sort adapter.
#
# References:
#   - Christophe Delage, Olivier Devillers, "CGAL Spatial Sorting User Manual",
#     CGAL 6.2, 2026.
#
# Algorithm:
#   - Build the optional `rch_cgal_spatial_sort` executable when CGAL is found.
#   - When tests are enabled, run a small adapter-level smoke test through CTest.
if(POLICY CMP0167)
    cmake_policy(SET CMP0167 NEW)
endif()

# The adapter does not call CGAL::data_file_path(), but Debian/Ubuntu CGAL
# package config warns unless a default data directory is defined.
if(NOT DEFINED CGAL_DATA_DIR AND EXISTS "${CMAKE_SOURCE_DIR}/data")
    set(
        CGAL_DATA_DIR
        "${CMAKE_SOURCE_DIR}/data"
        CACHE PATH "Default CGAL data directory for CGAL::data_file_path()"
    )
endif()

find_package(CGAL QUIET)

if(NOT CGAL_FOUND)
    message(WARNING "RCH_WITH_CGAL=ON but CGAL was not found; skipping A7 adapter target")
    return()
endif()

add_executable(rch_cgal_spatial_sort cgal_hilbert_sort_adapter.cpp)
target_link_libraries(rch_cgal_spatial_sort PRIVATE CGAL::CGAL rch::core)
target_compile_features(rch_cgal_spatial_sort PRIVATE cxx_std_23)

if(RCH_BUILD_TESTS)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_test(
        NAME CgalSpatialSortAdapter.Smoke
        COMMAND
            Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_cgal_spatial_sort_adapter.py"
            "$<TARGET_FILE:rch_cgal_spatial_sort>"
    )
endif()
