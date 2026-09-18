# tests/oracle/CMakeLists.txt — Hilbert/compact-Hilbert oracle tests
rch_provide_simdjson()

function(rch_add_oracle_test target_name)
    add_executable(${target_name} ${target_name}.cpp)
    target_link_libraries(
        ${target_name}
        PRIVATE rch::core GTest::gtest_main simdjson::simdjson
    )
    target_compile_definitions(
        ${target_name}
        PRIVATE RCH_TEST_ORACLE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
    )
    gtest_discover_tests(${target_name} DISCOVERY_MODE PRE_TEST)
endfunction()

rch_add_oracle_test(test_standard_hilbert_oracle)
rch_add_oracle_test(test_compact_hilbert_oracle)
rch_add_oracle_test(test_det_mcd_oracle)
rch_add_oracle_test(test_mrcd_oracle)
rch_add_oracle_test(test_ogk_oracle)
