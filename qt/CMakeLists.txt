cmake_minimum_required(VERSION 3.20)
set(ENCAP_VERSION "2.0.7" CACHE STRING "Version from the Cargo workspace")
project(EnCapQt VERSION ${ENCAP_VERSION} LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Widgets)
if(WIN32)
    enable_language(RC)
    set(ENCAP_WINDOWS_ICON "${CMAKE_CURRENT_SOURCE_DIR}/../assets/icons/EnCap.ico")
    set(ENCAP_WINDOWS_MANIFEST "${CMAKE_CURRENT_BINARY_DIR}/EnCap.manifest")
    configure_file(windows/EnCap.manifest.in "${ENCAP_WINDOWS_MANIFEST}" @ONLY)
    configure_file(windows/EnCap.rc.in "${CMAKE_CURRENT_BINARY_DIR}/EnCap.rc" @ONLY)
    set(ENCAP_WINDOWS_RESOURCES "${CMAKE_CURRENT_BINARY_DIR}/EnCap.rc")
endif()

add_subdirectory(../desktop/native ${CMAKE_CURRENT_BINARY_DIR}/native)
add_executable(EnCap WIN32 MACOSX_BUNDLE
    src/main.cpp
    src/engine_client.cpp
    src/engine_client.h
    src/main_window.cpp
    src/main_window.h
    assets.qrc
    ${ENCAP_WINDOWS_RESOURCES}
)
if(WIN32)
    target_link_options(EnCap PRIVATE "/MANIFEST:EMBED" "/MANIFESTINPUT:${ENCAP_WINDOWS_MANIFEST}")
endif()
target_link_libraries(EnCap PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets encap-playback)
if(TARGET encap-media)
    target_link_libraries(EnCap PRIVATE encap-media)
    target_compile_definitions(EnCap PRIVATE ENCAP_HAS_MEDIA_SESSION=1)
endif()
target_include_directories(EnCap PRIVATE ../desktop/native)
set_target_properties(EnCap PROPERTIES
    OUTPUT_NAME EnCap
    MACOSX_BUNDLE_BUNDLE_NAME "EnCap INTERNAL Qt Reference"
    MACOSX_BUNDLE_GUI_IDENTIFIER com.tlolabs.encap.qt-reference
    MACOSX_BUNDLE_INFO_STRING "Internal Qt reference; not a production Mac build"
)

include(CTest)
if(BUILD_TESTING)
    add_executable(encap-qt-tests tests/engine_client_test.cpp src/engine_client.cpp)
    target_include_directories(encap-qt-tests PRIVATE src)
    target_link_libraries(encap-qt-tests PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
    add_test(NAME encap-qt-engine-contract COMMAND encap-qt-tests)
    add_executable(encap-qt-ui-tests tests/ui_test.cpp src/main_window.cpp src/main_window.h
        src/engine_client.cpp src/engine_client.h assets.qrc)
    target_include_directories(encap-qt-ui-tests PRIVATE src ../desktop/native)
    target_link_libraries(encap-qt-ui-tests PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets encap-playback)
    if(TARGET encap-media)
        target_link_libraries(encap-qt-ui-tests PRIVATE encap-media)
        target_compile_definitions(encap-qt-ui-tests PRIVATE ENCAP_HAS_MEDIA_SESSION=1)
    endif()
    add_test(NAME encap-qt-widgets-accessibility COMMAND encap-qt-ui-tests)
    set_tests_properties(encap-qt-widgets-accessibility PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen" TIMEOUT 35)
endif()
