# Local production configuration

The accepted patch combination was moved from verbose diagnostics to a normal-use local deployment on 2026-11-12. The public repository remains source only. This is a custom Weston deployment for a pinned WSLg version, not an official Microsoft or upstream Weston binary release.

## Binary classification

The original backend and desktop builds used `-O2 -g`. Their accepted copies contained debugging information. The shell was copied from the installed WSLg system and had a GNU debug-link section; only its desktop-library dependency was rewritten.

The local production copies were created in a **new** runtime directory with `strip --strip-unneeded`, removing debug-link/mini-debug sections as well. The preparation tool checked that `.text`, dynamic exports, GLIBC requirements, and accepted input hashes were unchanged. No source was recompiled and no library assertions were removed. Thus these are optimized, stripped custom copies, not freshly compiled `NDEBUG` release builds.

| Module | Original accepted bytes | Stripped local bytes |
| --- | ---: | ---: |
| `rdp-backend.so` | 900400 | 178496 |
| `libweston-desktop-9.so.0` | 366408 | 76272 |
| `rdprail-shell.so` | 160369 | 135704 |
| Total | 1427177 | 390472 |

The shell's absolute dependency means its size depends on the local deployment path. These counts describe the tested machine, not a reproducible binary release. Removing debug information also does not remove every readable string or dynamic-linking symbol. None of these binaries is committed.

After reproducing the accepted builds and their reports described in [BUILD.md](BUILD.md), the included helper can create another fresh local directory:

```bash
python3 tools/prepare_production_modules.py \
  --destination runtime/production-candidate \
  --report evidence/production-candidate.json
```

It verifies the pinned build reports, copies modules, rewrites the copied shell dependency to the new desktop library, strips the new copies, and writes a deployment manifest. It does not change configuration or restart WSL. It rejects existing output directories/reports. Inspect the system-distro loader requirements, update the two module mappings, restart only after saving work, then verify actual process mappings. Do not overwrite or strip a loaded library in place.

## Lower-volume logs

The tested local production configuration uses these values in `.wslgconfig` under `[system-distro-env]`, in addition to the local module mappings:

```ini
WESTON_RDP_DEBUG_LEVEL=2
WESTON_RDPRAIL_SHELL_DEBUG_LEVEL=2
WESTON_RDP_DEBUG_CLIPBOARD_LEVEL=0
```

In the pinned Weston source, level 2 includes warning/error, while level 5 is verbose. Removing the diagnostic `WSLG_WESTON_LOG_PATH` override restores the standard `/mnt/wslg/weston.log`. Normal startup and error reporting remain enabled. Preserve unrelated settings and retain a private backup before edits.

## Electron startup

For the tested native-Wayland-capable Electron application, the ordinary startup selection is:

```bash
GALLIUM_DRIVER=d3d12 /absolute/path/to/electron-app --ozone-platform=wayland
```

For a project using the standard Electron CLI, run from its development directory:

```bash
GALLIUM_DRIVER=d3d12 npx electron . --ozone-platform=wayland
```

Framework development scripts may need their own argument-forwarding configuration. Check that the switch reaches Electron, rather than only a web development server. Desktop-file launches may not read interactive shell configuration; set the relevant environment in the application's user launcher when needed.

`bin/electron-wslg-native` is an optional ordinary-use wrapper. It sets the same driver/switch and clears historical tracing/injection variables. It also clears `NODE_OPTIONS` and `LD_PRELOAD`; use the direct command above for development sessions that intentionally require them. Keep the application's original executable and data profile.

The minimize fix needs no keepalive, background-throttle bypass, fractional-scale feature disable, or extra minimize-specific Electron switches. Do not disable the sandbox or force unsupported GL/ANGLE paths as a general startup recipe. Older Electron versions or app-specific GPU settings may require separate review.

`GALLIUM_DRIVER` selects the Mesa Gallium driver. `LIBVA_DRIVER_NAME` belongs to VA-API video-driver selection; it is not required to select OpenGL/D3D12 and does not prove video or window acceleration.

Native Wayland plus a D3D12 graphics path **does not establish Chromium hardware window compositing**. In this application's earlier diagnostics, `gpu_compositing` was `disabled_software`. The production smoke check observed a live GPU process with `/dev/dxg` and loaded D3D12 libraries, without remote debugging, but did not claim that the earlier compositing fallback had changed.

## Production smoke check

After restarting with the stripped copies and lower log levels, two complete physical input cycles hovered over the application's minimize button for about 800 ms, clicked it, restored through its current tray icon, and immediately scrolled conversation content. Both showed content movement without dragging, resizing, maximizing, or another content click. A preceding discovery cycle used an extra click and is not counted. Tray restoration reflects the application's current preference; it is distinct from the earlier taskbar-restoration series.

The original executable and application archive hashes were unchanged. No diagnostic supervisor was running. Private screenshots, launch records, process information, configuration backups, and full machine fingerprints stay outside this public repository. The check covers the reproduced path, not every application's internal minimize entry point.

## Primary references

- [Electron command-line switches](https://www.electronjs.org/docs/latest/api/command-line-switches#--ozone-platformplatform-linux)
- [Mesa environment variables](https://docs.mesa3d.org/envvars.html)
- [Mesa D3D12 driver](https://docs.mesa3d.org/drivers/d3d12.html)
- [Pinned WSLg log-path selection](https://github.com/microsoft/wslg/blob/6942bb534b537302a7a22617261d9274db3cfa37/WSLGd/main.cpp)
