cmake_minimum_required(VERSION 3.16)
project(fcitx5_waylandim_modifiers_backport VERSION 5.1.7 LANGUAGES C CXX)

# Only the WaylandIM addon and its private protocol wrappers are rebuilt.
# Core/config/utils remain the exact installed Ubuntu 5.1.7 libraries.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)
find_package(ECM REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH "${FCITX_SOURCE}/cmake" "${ECM_MODULE_PATH}")
find_package(Fcitx5Core 5.1.7 EXACT REQUIRED)
find_package(Wayland REQUIRED COMPONENTS Client)
find_package(WaylandScanner REQUIRED)
find_package(WaylandProtocols REQUIRED)
find_package(XKBCommon REQUIRED COMPONENTS XKBCommon)

# Public headers are identical to this source release. Generated export headers
# come from the matching Ubuntu development packages.
get_target_property(UTILS_INCLUDES Fcitx5::Utils INTERFACE_INCLUDE_DIRECTORIES)
get_target_property(CORE_INCLUDES Fcitx5::Core INTERFACE_INCLUDE_DIRECTORIES)
get_target_property(CONFIG_INCLUDES Fcitx5::Config INTERFACE_INCLUDE_DIRECTORIES)
foreach(dir IN LISTS UTILS_INCLUDES CORE_INCLUDES CONFIG_INCLUDES)
    include_directories("${dir}/fcitx-utils" "${dir}/fcitx" "${dir}/fcitx-config")
endforeach()
include_directories("${CMAKE_CURRENT_SOURCE_DIR}" "${FCITX_SOURCE}/src/lib")
add_compile_options("-ffile-prefix-map=${FCITX_SOURCE}=fcitx5-5.1.7")

foreach(part core input-method input-method-v2 plasma-window-management wlr-foreign-toplevel-management-unstable-v1)
    add_subdirectory("${FCITX_SOURCE}/src/lib/fcitx-wayland/${part}" "protocols/${part}")
endforeach()
ecm_add_wayland_client_protocol(TEXT_PROTOCOLS
    PROTOCOL ${WAYLAND_PROTOCOLS_PKGDATADIR}/unstable/text-input/text-input-unstable-v1.xml
    BASENAME text-input-unstable-v1)
ecm_add_wayland_client_protocol(TEXT_PROTOCOLS
    PROTOCOL ${WAYLAND_PROTOCOLS_PKGDATADIR}/unstable/text-input/text-input-unstable-v3.xml
    BASENAME text-input-unstable-v3)

set(WAYLANDIM_DIR "${FCITX_SOURCE}/src/frontend/waylandim")
set(WAYLANDIM_SOURCES waylandim.cpp waylandimserverbase.cpp waylandimserver.cpp
    waylandimserverv2.cpp plasmaappmonitor.cpp virtualinputcontext.cpp
    wlrappmonitor.cpp appmonitor.cpp)
list(TRANSFORM WAYLANDIM_SOURCES PREPEND "${WAYLANDIM_DIR}/")
add_library(waylandim MODULE ${WAYLANDIM_SOURCES} ${TEXT_PROTOCOLS})
target_include_directories(waylandim PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"
    "${FCITX_SOURCE}/src/modules/wayland")
target_link_libraries(waylandim PRIVATE Fcitx5::Core Wayland::Client
    XKBCommon::XKBCommon Fcitx5::Wayland::PlasmaWindowManagement
    Fcitx5::Wayland::WLRForeignToplevelManagement Fcitx5::Wayland::Core
    Fcitx5::Wayland::InputMethod Fcitx5::Wayland::InputMethodV2)
target_link_options(waylandim PRIVATE -Wl,-z,defs)
