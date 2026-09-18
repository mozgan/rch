# tests/integration/CMakeLists.txt - integration-level smoke tests.
set(Python3_FIND_VIRTUALENV FIRST)
find_package(Python3 COMPONENTS Interpreter REQUIRED)

add_test(
    NAME reference_r_baselines
    COMMAND
        Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_reference_r_baselines.py"
)
set_tests_properties(
    reference_r_baselines
    PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}"
)
