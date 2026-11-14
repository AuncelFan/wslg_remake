# Production settings for native Wayland IME

Recorded on 2026-11-14 for WSLg 1.0.79. These are optimized, stripped custom
modules, not official Microsoft/Weston releases. The repository is source only.

## Settings changed for normal use

| Location | Production change |
| --- | --- |
| Windows `.wslgconfig` | Module/config paths now select one new production runtime; existing warning/error and clipboard-off levels retained |
| Runtime `config/weston.ini` | Helper path selects the production relay; original Xwayland setting retained |
| `~/.local/bin/chatgpt` | Retain Wayland, IME v1 and D3D12; remove three experimental switches and clear inherited tracing/injection settings |
| User `wslg-ime.service` | Run the production supervisor snapshot; discard inherited diagnostic variables |
| Fcitx arguments | Reduce default Info logs to Warn/Error/Fatal; explicitly disable key tracing |
| `~/.zshrc` | Remove the exact legacy `export LIBVA_DRIVER_NAME=d3d12`; retain `GALLIUM_DRIVER=d3d12` |
| `~/.zshenv` | Content unchanged; continue starting the managed service |

Application package files, profiles, dictionaries, system components,
`.wslconfig` and the user desktop entry are not replaced.

## WSLg configuration

Replace `<RUNTIME>` with the actual absolute Linux production path. This is
documentation syntax, not an environment variable expanded by WSLg.

```ini
[system-distro-env]
XDG_CONFIG_HOME=<RUNTIME>/config
WSLG_IME_BRIDGE_SOCKET=/mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock
WESTON_MODULE_MAP=rdp-backend.so=<RUNTIME>/rdp-backend.so;rdprail-shell.so=<RUNTIME>/rdprail-shell.so
WESTON_RDP_DEBUG_LEVEL=2
WESTON_RDPRAIL_SHELL_DEBUG_LEVEL=2
WESTON_RDP_DEBUG_CLIPBOARD_LEVEL=0
```

Level 2 in the pinned RDP code includes warning/error. No custom log path or
protocol/key trace is enabled; normal WSLg startup/error reporting remains.
The runtime's `config/weston.ini` is:

```ini
[xwayland]
disable_access_control=true

[input-method]
path=<RUNTIME>/trusted-socket-relay
```

## Original-application launcher

The complete script is [chatgpt_wayland_wrapper.sh](../tools/ime/chatgpt_wayland_wrapper.sh).
Its normal command is:

```bash
OZONE_PLATFORM=wayland GALLIUM_DRIVER=d3d12 /usr/bin/chatgpt \
  --ozone-platform=wayland \
  --enable-wayland-ime \
  --wayland-text-input-version=1
```

Removed switches: `--disable-background-timer-throttling`,
`--disable-renderer-backgrounding`, and
`--disable-features=WaylandFractionalScaleV1`. No remote-debugging, GPU-disable
or sandbox-disable switch is added.

The launcher clears inherited Wayland/Electron/Mesa/GL tracing, known project
injection settings, `NODE_OPTIONS`, `LD_PRELOAD`, and legacy software/VA-API
overrides for its process tree. Development sessions intentionally using
these variables should use a direct command. `LIBVA_DRIVER_NAME` selects a
video driver; it is not required for the Mesa OpenGL D3D12 path.

## Managed Fcitx session

```text
fcitx5 -D --keep --enable=wayland,waylandim --option=wayland=nodefault --verbose=*=3,key_trace=0
```

Despite its name, `--verbose` configures logging rules: 3 is Warn (plus
Error/Fatal); `key_trace=0` disables key tracing. Broker/supervisor logs retain
a few lifecycle events and normal errors, without typed text or keys.

The installer quotes the real runtime path and escapes systemd `%` specifiers:

```ini
[Unit]
Description=WSLg trusted native Wayland Fcitx session
After=dbus.socket
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus
Environment=XDG_RUNTIME_DIR=%t
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=LANG=zh_CN.UTF-8
Environment=GALLIUM_DRIVER=d3d12
UnsetEnvironment=WAYLAND_SOCKET WAYLAND_DEBUG LD_PRELOAD NODE_OPTIONS MESA_DEBUG MESA_LOG_FILE LIBGL_DEBUG
ExecStart=/usr/bin/python3 "<RUNTIME>/ime/session_supervisor.py" --socket /mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock
Restart=on-failure
RestartSec=3
KillMode=mixed
TimeoutStopSec=12
UMask=0077
SyslogIdentifier=wslg-ime

[Install]
WantedBy=default.target
```

`.zshenv` retains this idempotent trigger; the enabled unit also starts with
the user manager:

```sh
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start --no-block wslg-ime.service >/dev/null 2>&1
fi
```

## Promotion, rollback and update checks

The preparation tool verifies accepted candidate hashes, copies backend,
shell, desktop library and relay into a fresh directory, and relocates the
copied shell's absolute desktop dependency into that same directory. It strips
debug/debug-link sections and verifies `.text`, dynamic exports and GLIBC
requirements. It does not recompile code or disable assertions.

After building/accepting a candidate and saving other WSL work, use the
private manifest printed by the candidate installer:

```powershell
.\tools\ime\activate_production.ps1 `
  -UpgradeFrom '/absolute/private/candidate-backup/manifest.json' `
  -RestartWsl
```

The script checks pinned WSLg/Weston versions and current mappings, prepares
new outputs, runs `ldd -r` using the actual system-distro loader, validates
current user-file hashes, backs up settings and updates them. Outputs must
be fresh. Review the tools before adapting them to another version.

The generated private rollback restores the candidate config and user
settings, including the previous enabled-service state, then restarts WSL.
It refuses to overwrite settings changed after deployment. Keep the old
runtime and private backups for rollback. Never overwrite/delete mapped libs.

After a WSLg update, check `/mnt/wslg/versions.txt`, Weston/FreeRDP commits,
GLIBC and loader/ABI compatibility before loading these modules. Verify real
process mappings; config text alone does not prove deployment. Unchanged
fingerprints do not prove GUI correctness.

## Recorded checks and publication boundary

The live compositor mapped all three production libraries. The enabled user
service had a trusted handoff and no restart loop. The original application
restarted with native Wayland/IME v1, no experimental/debug switches, unchanged
package/ELF/ASAR integrity, and a D3D12 GPU process holding `/dev/dxg`.
Four isolated installer tests cover promotion, exact rollback, enabled-state
restoration and refusal to overwrite changed settings. Nine FD tests pass.

The user accepted the preceding IME candidate. This cleanup adds no new
physical-input acceptance claim; the earlier hardware-window-compositing
limitation remains. This is not a universal or long-duration stability claim.

Machine paths, raw logs, screenshots, profiles, account data, SDKs, private
backups and binary artifacts stay local and are not published.
