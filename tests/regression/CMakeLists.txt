rch_provide_simdjson()

add_executable(test_reproducibility test_reproducibility.cpp)
target_link_libraries(
    test_reproducibility
    PRIVATE rch::core GTest::gtest_main simdjson::simdjson
)
target_include_directories(
    test_reproducibility
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../oracle"
)
target_compile_definitions(
    test_reproducibility
    PRIVATE RCH_REGRESSION_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
)
gtest_discover_tests(test_reproducibility DISCOVERY_MODE PRE_TEST)

add_executable(test_cross_toolchain test_cross_toolchain.cpp)
target_link_libraries(
    test_cross_toolchain
    PRIVATE rch::core GTest::gtest_main simdjson::simdjson
)
target_include_directories(
    test_cross_toolchain
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../oracle"
)
target_compile_definitions(
    test_cross_toolchain
    PRIVATE
        RCH_EXPECTED_OUTPUTS_DIR="${CMAKE_SOURCE_DIR}/reproducibility/expected_outputs"
)
gtest_discover_tests(test_cross_toolchain DISCOVERY_MODE PRE_TEST)
