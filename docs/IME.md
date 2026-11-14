# Native Wayland IME support on the tested WSLg baseline

The original installed application is retained. A Weston patch and a trusted
connection bridge connect Fcitx5 to the native Wayland input path. The user
reported success after receiving the physical test steps on 2026-11-14.
This is user feedback, not an automated physical-input result.

## Three integration gaps

1. The tested Chromium needs `--enable-wayland-ime` together with
   `--wayland-text-input-version=1` to select the protocol exposed by this Weston.
2. Weston authorizes the input-method client that it launches. An ordinary
   Fcitx connection is refused; the trusted `WAYLAND_SOCKET` must reach Fcitx
   without removing the compositor's identity check.
3. The pinned RAIL shell's native input-panel implementation was a stub.
   A working text connection alone did not implement candidate-window mapping.

GTK applications can use a toolkit input module. Their success does not prove
that Chromium's native Wayland input context is connected.

## Implemented path

```text
Original application -- text-input-v1 -- Weston -- input-method-v1 -- Fcitx5
                                          |
                          input-panel view + RAIL popup -> Windows

Weston-created trusted FD -> system-distro relay -> SCM_RIGHTS
                         -> Ubuntu broker -> Fcitx user-session DBus
```

The relay inherits the compositor-created FD. The broker calls Fcitx's
existing `OpenWaylandConnectionSocket` on an already-running unique DBus owner,
without auto-activation. The shared Linux directory is mode 0700; the control
socket is 0600, and both peers check UID. It is not placed on DrvFS.

The supervisor owns Fcitx and the broker. Either child exiting ends the
session; systemd restarts both, avoiding another parser on a stale Wayland
stream. There is no per-key Python relay, clipboard insertion, application
JavaScript injection or application binary modification.

## Weston patch

`0003-rdprail-native-input-panels.patch` changes five files, +557 / -171,
on top of the two accepted minimize patches:

| File | Change |
| --- | --- |
| `rdprail-shell/input-panel.c` | Panel view/layer, role, mapping, cursor/workarea positioning, parent/output listeners and cleanup |
| `rdprail-shell/shell.h` | Panel state and listeners |
| `rdprail-shell/shell.c` | Explicit hiding on minimize and safe teardown ordering |
| `include/libweston/backend-rdp.h` | Separate versioned panel API; existing RAIL API table unchanged |
| `libweston/backend-rdp/rdprail.c` | Owned no-activate popups, state-only hiding, owner detach and activation handling |

Hiding does not depend on a buffer, output-mask iteration or graphics ACK.
The candidate is not selected as the active host window. Other application
window roles retain their behavior.

This rebuilds `rdp-backend.so` and `rdprail-shell.so`, reuses the accepted
patched `libweston-desktop-9.so.0`, and compiles a small relay. Core text-backend,
libexec and Fcitx source are not rebuilt.

## Recorded snapshot and checks

- WSL 3.0.5.0; WSLg 1.0.79; Weston
  `a7e35fdab455dce5774b43b8aff682f748307e31`.
- FreeRDP `c4030980b29322a9cb2190711a5fadeeeb8b6a33`.
- Azure Linux 3.0 system distro, glibc 2.38; Ubuntu 24.04 LTS.
- Fcitx5 `5.1.7-1build3`; Chinese addons `5.1.3-1build3`.
- Original application package `26.1106.51428`, Chromium `157.0.8103.51`;
  Mesa 25.2.8 D3D12 renderer. These are snapshots, not promises for later updates.

Nine transport tests cover valid FD delivery and malformed/unauthorized paths.
An isolated stock text backend with actual Fcitx produced native preedit and
Chinese commits. Panel checks cover mapping, positioning, parent movement,
workarea bounds, hide/show, minimize, destruction and reuse; the fixture's
RAIL transport is mocked. Supervisor failure/restart was also exercised.
These isolated tests do not establish Windows popup visibility or GUI input.

The user reported success for the deployed original-application solution.
Individual multi-output/scale cases, every internal minimize path, other-app
regressions and long-duration stability were not separately reported.
The subsequent production cleanup verified live mappings, a trusted handoff,
a clean original application and D3D12 plus `/dev/dxg`; it does not add a new
physical-input acceptance result. Chromium hardware window compositing
previously reported `disabled_software`; D3D12 rendering does not prove it.

See [production settings](IME_PRODUCTION.md), [build notes](BUILD.md), and
[bridge tools](../tools/ime/README.md).

## Pinned primary sources

- [Weston authorization](https://github.com/microsoft/weston-mirror/blob/a7e35fdab455dce5774b43b8aff682f748307e31/compositor/text-backend.c)
- [Original panel stub](https://github.com/microsoft/weston-mirror/blob/a7e35fdab455dce5774b43b8aff682f748307e31/rdprail-shell/input-panel.c)
- [Chromium v1 selection](https://github.com/chromium/chromium/blob/157.0.8103.51/ui/ozone/platform/wayland/host/wayland_input_method_context.cc)
- [Fcitx FD launcher](https://github.com/fcitx/fcitx5/blob/5.1.7/src/tools/wayland-launcher.cpp)
- [Fcitx Wayland module](https://github.com/fcitx/fcitx5/blob/5.1.7/src/modules/wayland/waylandmodule.cpp)
