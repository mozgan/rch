# tests/fuzz/CMakeLists.txt — libFuzzer harnesses.

function(rch_add_fuzz_target target_name)
    add_executable(${target_name} ${target_name}.cpp)
    target_include_directories(${target_name} PRIVATE "${CMAKE_SOURCE_DIR}")
    target_link_libraries(${target_name} PRIVATE rch::core)
    target_compile_options(${target_name} PRIVATE -fsanitize=fuzzer-no-link)
    target_link_options(${target_name} PRIVATE -fsanitize=fuzzer)
endfunction()

rch_add_fuzz_target(fuzz_quantizer)
rch_add_fuzz_target(fuzz_sfc_keys)
rch_add_fuzz_target(fuzz_preprocessing)
