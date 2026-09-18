# benchmarks/CMakeLists.txt - Google Benchmark micro-benchmark targets.
#
# References:
#   Google, Google Benchmark User Guide.
#   ISO/IEC, Programming Languages - C++, 2020.

rch_provide_benchmark()

function(rch_add_benchmark target_name)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${target_name}.cpp")
        message(STATUS "RCH benchmark ${target_name}: source file is absent; target skipped")
        return()
    endif()
    add_executable(${target_name} ${target_name}.cpp)
    target_link_libraries(${target_name}
        PRIVATE rch::core
                benchmark::benchmark
                benchmark::benchmark_main
    )
endfunction()

rch_add_benchmark(bench_quantization)
rch_add_benchmark(bench_sfc_keygen)
rch_add_benchmark(bench_sort)
rch_add_benchmark(bench_metrics_knn)
rch_add_benchmark(bench_ordering)
rch_add_benchmark(bench_detmcd)
rch_add_benchmark(bench_io)

if(RCH_BUILD_TESTS)
    add_executable(bench_common_selftest bench_common_selftest.cpp)
    target_link_libraries(bench_common_selftest PRIVATE benchmark::benchmark)
    add_test(NAME BenchCommon.ProcessedItemsSaturates COMMAND bench_common_selftest)
endif()
