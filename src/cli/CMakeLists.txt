# src/cli/CMakeLists.txt - developer CLI targets.
function(rch_add_cli target_name)
    add_executable(${target_name} ${target_name}.cpp)
    target_link_libraries(${target_name} PRIVATE rch::core)
endfunction()

rch_add_cli(rch_order)
rch_add_cli(rch_compare_orders)
rch_add_cli(rch_block_read_probe)

if(RCH_BUILD_TESTS)
    set(Python3_FIND_VIRTUALENV FIRST)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_test(
        NAME cli_tools_smoke
        COMMAND
            Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_cli_tools.py"
    )
    set_tests_properties(
        cli_tools_smoke
        PROPERTIES
            ENVIRONMENT
                "RCH_ORDER_BIN=$<TARGET_FILE:rch_order>;RCH_COMPARE_ORDERS_BIN=$<TARGET_FILE:rch_compare_orders>;RCH_BLOCK_READ_PROBE_BIN=$<TARGET_FILE:rch_block_read_probe>"
    )
endif()
