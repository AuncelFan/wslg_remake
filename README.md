# wslg_remake

Weston patches that fix the reproduced **WSLg application freeze after minimizing and restoring a window** on the tested WSLg 1.0.79 / Weston 9.0.0 configuration.

本项目通过修改 WSLg 使用的 Weston，修复已复现的应用内最小化后恢复卡死问题。应用保持原版，不依赖应用补丁、JavaScript 注入或后台重绘保活。

2026-11-14：新增原生 Wayland 中文输入支持。保留原版应用，通过受信任的 Fcitx 连接和 Weston/RAIL 候选窗实现，用户已反馈当前方案成功。已转为低日志生产配置；公开仓库继续仅含源码，不含本机二进制、日志和用户数据。详见 [输入法实现](docs/IME.md) 与 [当前生产配置](docs/IME_PRODUCTION.md)。

2026-11-16：新增 Fcitx5 5.1.7 原生 Wayland 快捷键修复，补齐输入法转发的 Ctrl/Shift 等修饰键状态。此项单独回补 Fcitx WaylandIM 模块，不增加 Weston 改动，目标应用保持原版。附带限定版本的构建配置、服务级加载守卫及回退说明。详见 [快捷键诊断](docs/shortcut-diagnosis-20261116.md) 与 [构建/部署说明](tools/ime/fcitx-waylandim/README.md)。

2026-11-16: fixed HiDPI cursor bitmap/hotspot scaling and double-scaled cursor
buffers in the RDP backend. Patch 0004 passed 36 physical calibration clicks
across two outputs and two cursor buffer scales using native Wayland + D3D12.
See the [pointer alignment record](docs/POINTER_ALIGNMENT.md).

2026-11-18: added a Windows work-area synchronization helper for maximized
Wayland windows whose contents were clipped by the taskbar. It dynamically
observes monitor/work-area/DPI and WSLg connection changes, then asks MSRDC to
re-send work areas through the existing RAIL channel. This addition needs no
new Weston patch and preserves the original application. Only source is
distributed; see [build, installation, startup, status and removal instructions](docs/WORKAREA_SYNC.md).

## What changed

The two minimize patches modify four Weston source files: **83 added lines
and 3 deleted lines**, including comments. The additional IME patch modifies
five files (+557 / -171). The cursor patch modifies two existing backend
files (+36 / -5); there are eight distinct source files across all four patches.

| Patch | Purpose | Changes |
| --- | --- | --- |
| [0001](patches/weston/0001-rdp-resume-deferred-repaint-on-ack.patch) | Resume deferred RAIL repaint when a frame/buffer ACK releases backpressure | 3 files, +77 / −1 |
| [0002](patches/weston/0002-xdg-shell-compare-last-acked-state.patch) | Compare pending xdg-shell state with the last acknowledged configuration instead of stale committed state | 1 file, +6 / −2 |
| [0003](patches/weston/0003-rdprail-native-input-panels.patch) | Map native input panels as owned, non-activating RAIL popups and manage their lifecycle | 5 files, +557 / −171 |
| [0004](patches/weston/0004-rdprail-scale-cursor-hotspot.patch) | Scale cursor bitmaps and hotspots consistently, avoid applying buffer scale twice, and send hotspot-only updates | 2 files, +36 / -5 |

The separate [Fcitx5 patch](patches/fcitx5/0001-waylandim-v1-forward-modifiers.patch)
adds one `modifiers()` request to the 5.1.7 WaylandIM frontend (+2 lines,
including a blank line). Its scoped build and session guard are additional
integration tools. No extra Weston source changes are needed for this fix.

The second patch addresses the reproduced minimize/restore failure: a bufferless commit can leave `current.activated` stale. Comparing against that stale state can suppress the activation configure required to restore the client. When the configure queue is empty, the patch compares against `next.state`, the last acknowledged state.

The first patch wakes repaint work previously deferred by RDP/RAIL backpressure. It remains part of the accepted combination, but did not independently solve the hover/minimize failure. Its independent necessity for that particular failure has not been established.

## Tested baseline

- WSL: **3.0.5.0**, WSLg: **1.0.79**.
- Weston: **9.0.0**, Microsoft commit `a7e35fdab455dce5774b43b8aff682f748307e31`.
- FreeRDP: commit `c4030980b29322a9cb2190711a5fadeeeb8b6a33`.
- WSLg system distro: Azure Linux 3.0, glibc 2.38.
- Build environment: Ubuntu 24.04 LTS, GCC 13.3.0.
- Native Wayland with a D3D12 renderer.

The application-button test sequence moves the pointer onto the minimize button, waits about 800 ms, clicks, then restores through the Windows taskbar. An immediate pointer jump-and-click can miss the original failure.

The accepted combination completed 23 application-button cycles; 22 included explicit content scrolling, while one reached the scroll boundary. The unchanged-source rebuilt control still froze. The xdg-shell state replay checks 330 assertions. The RAIL regression harness exercises 18 scenarios against both baseline and patched source.

These results describe the tested failure and configuration, not every application or every internal minimize entry point. The tested application's window GPU compositing still reported `disabled_software` despite its D3D12 renderer. The auxiliary native EGL/GLES Wayland test does not turn that into a hardware-window-compositing claim.

## Deployment model

The current combination uses rebuilt `rdp-backend.so`,
`libweston-desktop-9.so.0` and `rdprail-shell.so`, plus a small trusted-FD relay.
The IME build reuses the accepted minimize-patched desktop library.
`WESTON_MODULE_MAP` selects the replacement backend and shell. The production
shell dependency points to the desktop library in the same new runtime.
The pointer follow-up replaces only the backend in a separate immutable
runtime; the accepted IME shell and its desktop-library dependency remain
together. See the [pointer deployment record](docs/POINTER_ALIGNMENT.md).

On the tested Ubuntu Fcitx 5.1.7 configuration, the shortcut fix additionally
loads a user-local `libwaylandim.so` through a `wslg-ime.service` drop-in.
The launcher checks exact Fcitx package versions and the module checksum,
falling back to system addons on mismatch. It does not replace package-owned
Fcitx files or modify the target application.

The work-area follow-up adds a hidden, per-user Windows helper and a Startup
shortcut. It runs while automatic synchronization is desired; it is not a
Windows system service. Installation compiles an optimized executable locally
and leaves the existing Weston modules, WSLg configuration and application
wrapper intact. Its bounds come from the current Windows monitor/work-area
APIs, with no fixed taskbar height or primary-monitor dimensions. See the
[work-area deployment instructions](docs/WORKAREA_SYNC.md).

Installed system components are preserved. Before the IME extension, the
minimize-only deployment used a stock shell copy with its dependency rewritten;
the IME extension rebuilds the shell source. No machine-bound `.so` artifacts
or ready-made local configuration are shipped.

See [build/test notes](docs/BUILD.md), [current IME production settings](docs/IME_PRODUCTION.md), [historical minimize-only production notes](docs/PRODUCTION.md), and [WSL update maintenance](docs/MAINTENANCE.md). The scripts are developer tools for the pinned baseline, not a universal installer. Rebuild against the matching WSLg SDK and review changes before deploying on another version.

## Public contents

This source-only repository contains patches, selected build/deployment/regression tools, and sanitized technical notes. It excludes local profiles, account data, screenshots, conversation content, runtime logs, raw environment snapshots, SDK archives, application packages, and machine-bound binaries.

The upstream Weston copyright and license notice is retained in [LICENSE.weston](LICENSE.weston).
