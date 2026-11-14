#!/usr/bin/env bash
# Original installed application, native Wayland v1 IME and Mesa D3D12.
set -euo pipefail
# Normal-use launcher: do not inherit earlier project tracing or injection.
unset WAYLAND_DEBUG ELECTRON_ENABLE_LOGGING ELECTRON_LOG_FILE
unset MESA_DEBUG MESA_LOG_FILE LIBGL_DEBUG
unset LIBGL_ALWAYS_SOFTWARE MESA_LOADER_DRIVER_OVERRIDE LIBVA_DRIVER_NAME
unset NODE_OPTIONS LD_PRELOAD ELECTRON_RUN_AS_NODE
unset WSLG_FIX WSLG_FIX_MODE WSLG_FIX_LOG
export OZONE_PLATFORM=wayland
export GALLIUM_DRIVER=d3d12
exec /usr/bin/chatgpt \
    --ozone-platform=wayland \
    --enable-wayland-ime \
    --wayland-text-input-version=1 \
    "$@" < /dev/null
