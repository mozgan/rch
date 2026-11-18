# src/cli/CMakeLists.txt - developer CLI targets.
function(rch_add_cli target_name)
    add_executable(${target_name} ${target_name}.cpp)
    target_link_libraries(${target_name} PRIVATE rch::core)
endfunction()

rch_add_cli(rch_order)
rch_add_cli(rch_compare_orders)
rch_add_cli(rch_block_read_probe)
rch_add_cli(rch_application_query_smoke)
rch_add_cli(rch_clamping_ablation)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    rch_add_cli(rch_application_cache_probe)
    rch_add_cli(rch_application_workflow)
endif()

if(RCH_BUILD_TESTS)
    set(Python3_FIND_VIRTUALENV FIRST)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        add_test(NAME ApplicationCache.Smoke
            COMMAND Python3::Interpreter
                "${CMAKE_SOURCE_DIR}/tests/integration/test_application_cache.py"
                "$<TARGET_FILE:rch_application_query_smoke>"
                "$<TARGET_FILE:rch_application_cache_probe>")
        add_test(NAME ApplicationWorkflow.Smoke
            COMMAND Python3::Interpreter
                "${CMAKE_SOURCE_DIR}/tests/integration/test_application_workflow_e2e.py"
                "$<TARGET_FILE:rch_application_workflow>")
        add_test(NAME ApplicationIOArtifacts.Smoke
            COMMAND Python3::Interpreter
                "${CMAKE_SOURCE_DIR}/tests/integration/test_application_io_artifacts.py")
    endif()
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
    add_test(
        NAME ClampingIntervention.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_clamping_ablation.py"
            "$<TARGET_FILE:rch_clamping_ablation>"
    )
    add_test(NAME OrderMeasurementIntegrity.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_order_measurement_integrity.py"
            "$<TARGET_FILE:rch_order>")
    add_test(NAME FallbackCliEvidence.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_fallback_cli_evidence.py"
            "$<TARGET_FILE:rch_order>")
    add_test(
        NAME FrameStability.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_frame_stability.py"
            "$<TARGET_FILE:rch_order>"
    )
    add_test(
        NAME RegimeBenchmarks.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_regime_benchmarks.py"
            "$<TARGET_FILE:rch_order>"
    )
    add_test(
        NAME CostDecomposition.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_cost_decomposition.py"
            "$<TARGET_FILE:rch_order>"
    )
    add_test(
        NAME ApplicationNativeRules.Smoke
        COMMAND Python3::Interpreter
            "${CMAKE_SOURCE_DIR}/tests/integration/test_application_native_rules.py"
            "$<TARGET_FILE:rch_order>" "$<TARGET_FILE:rch_application_query_smoke>"
    )
endif()
