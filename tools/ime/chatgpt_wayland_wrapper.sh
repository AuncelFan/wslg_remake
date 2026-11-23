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
launch=(/usr/bin/chatgpt
    --ozone-platform=wayland
    --enable-wayland-ime
    --wayland-text-input-version=1)

# A launch during shutdown can be acknowledged by Electron's old singleton,
# even though that process then exits without leaving a window. Retry a plain
# launch once if that exact application instance exits soon after the handoff.
# Leave launches with explicit arguments to Electron's normal handling.
if (( $# == 0 )); then
    profile="${XDG_CONFIG_HOME:-$HOME/.config}/Codex"
    lock="$(readlink -- "$profile/SingletonLock" 2>/dev/null || :)"
    owner="${lock##*-}"
    if [[ "$owner" =~ ^[1-9][0-9]*$ &&
          "/proc/$owner/exe" -ef /usr/lib/chatgpt/ChatGPT ]]; then
        owner_stat="$(cat "/proc/$owner/stat" 2>/dev/null || :)"
        read -r -a owner_fields <<< "${owner_stat##*) }"
        owner_start="${owner_fields[19]-}"
        if [[ -n "$owner_start" ]]; then
            deadline=$((SECONDS + 10))
            "${launch[@]}" < /dev/null
            while (( SECONDS < deadline )); do
                owner_stat="$(cat "/proc/$owner/stat" 2>/dev/null || :)"
                read -r -a owner_fields <<< "${owner_stat##*) }"
                if [[ "${owner_fields[19]-}" != "$owner_start" ||
                      "${owner_fields[0]-}" == Z ]]; then
                    exec "${launch[@]}" < /dev/null
                fi
                sleep 0.1
            done
            exit 0
        fi
    fi
fi
exec "${launch[@]}" "$@" < /dev/null
