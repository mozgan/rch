# cmake/InstallRules.cmake - install/export rules for the header-only core.

include_guard(GLOBAL)

include(GNUInstallDirs)

option(RCH_ENABLE_INSTALL "Enable CMake install rules" ON)

function(rch_install_rules)
    if(NOT RCH_ENABLE_INSTALL)
        return()
    endif()

    install(
        TARGETS rch_core rch_warnings rch_sanitizers rch_repro_fp rch_coverage
        EXPORT rchTargets
    )

    install(
        DIRECTORY "${PROJECT_SOURCE_DIR}/include/"
        DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    )

    install(
        DIRECTORY "${PROJECT_BINARY_DIR}/generated/include/"
        DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    )

    install(
        EXPORT rchTargets
        NAMESPACE rch::
        DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/rch"
    )
endfunction()
