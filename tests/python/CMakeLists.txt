# tests/python/CMakeLists.txt — Python generator/analysis smoke tests.
#
set(Python3_FIND_VIRTUALENV FIRST)
find_package(Python3 COMPONENTS Interpreter REQUIRED)
message(STATUS "RCH Python tests interpreter: ${Python3_EXECUTABLE}")

add_test(
    NAME synthetic_python_pipeline
    COMMAND
        Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_synthetic_pipeline.py"
)
set_tests_properties(
    synthetic_python_pipeline
    PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}"
)

add_test(
    NAME real_python_pipeline
    COMMAND
        Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_real_pipeline.py"
)
set_tests_properties(
    real_python_pipeline
    PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}"
)

add_test(
    NAME paper_artifacts_python
    COMMAND
        Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_paper_artifacts.py"
)
set_tests_properties(
    paper_artifacts_python
    PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}"
)

add_test(
    NAME scripts_python_tools
    COMMAND
        Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_scripts.py"
)
set_tests_properties(
    scripts_python_tools
    PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}"
)

add_test(
    NAME application_workflow_python
    COMMAND Python3::Interpreter -m unittest discover -s
        "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_application_workflow.py"
)
set_tests_properties(application_workflow_python PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}")

add_test(NAME download_retry_python
    COMMAND Python3::Interpreter -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_download_retry.py")
set_tests_properties(download_retry_python PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}")

add_test(NAME review_followup_python
    COMMAND Python3::Interpreter -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_review_followup.py")
set_tests_properties(review_followup_python PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}" TIMEOUT 30)

add_test(NAME fallback_evidence_python
    COMMAND Python3::Interpreter -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_fallback_evidence.py")
set_tests_properties(fallback_evidence_python PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}")

foreach(suite IN ITEMS benchmark_resume measurement_diagnostics cost_stability_decisions build_workflows)
    add_test(NAME ${suite}_python
        COMMAND Python3::Interpreter -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_${suite}.py")
    set_tests_properties(${suite}_python PROPERTIES ENVIRONMENT "PYTHONPATH=${CMAKE_SOURCE_DIR}")
endforeach()
