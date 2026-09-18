# examples/CMakeLists.txt - small programs that consume the public header-only API.

add_executable(rch_basic_order basic_order.cpp)
target_link_libraries(rch_basic_order PRIVATE rch::core)
