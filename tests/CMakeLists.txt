# tests/CMakeLists.txt — RCH unit/property/regression test entry point.
include(GoogleTest)

add_subdirectory(unit)
add_subdirectory(oracle)
add_subdirectory(regression)
add_subdirectory(property)
add_subdirectory(python)
add_subdirectory(integration)
if(RCH_BUILD_FUZZ)
    add_subdirectory(fuzz)
endif()
