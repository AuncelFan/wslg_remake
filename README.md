# wslg_remake

Weston patches that fix the reproduced **WSLg application freeze after minimizing and restoring a window** on the tested WSLg 1.0.79 / Weston 9.0.0 configuration.

本项目通过修改 WSLg 使用的 Weston，修复已复现的应用内最小化后恢复卡死问题。应用保持原版，不依赖应用补丁、JavaScript 注入或后台重绘保活。

## What changed

Two patches modify four Weston source files: **83 added lines and 3 deleted lines**, including comments.

| Patch | Purpose | Changes |
| --- | --- | --- |
| [0001](patches/weston/0001-rdp-resume-deferred-repaint-on-ack.patch) | Resume deferred RAIL repaint when a frame/buffer ACK releases backpressure | 3 files, +77 / −1 |
| [0002](patches/weston/0002-xdg-shell-compare-last-acked-state.patch) | Compare pending xdg-shell state with the last acknowledged configuration instead of stale committed state | 1 file, +6 / −2 |

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

Two components are rebuilt: `rdp-backend.so` and `libweston-desktop-9.so.0`. A copy of the installed `rdprail-shell.so` has its desktop-library dependency redirected to the rebuilt library. `WESTON_MODULE_MAP` selects the replacement backend and shell copy.

Installed system components are preserved. The shell is copied and its ELF dependency rewritten; its source is not rebuilt. This repository does not ship the machine-specific `.so` artifacts or a ready-made configuration.

See [build and test notes](docs/BUILD.md) and [WSL update maintenance](docs/MAINTENANCE.md). The scripts are developer tools for the pinned baseline, not a universal installer. Rebuild against the matching WSLg SDK and review changes before deploying on another version.

## Public contents

This source-only repository contains patches, selected build/deployment/regression tools, and sanitized technical notes. It excludes local profiles, account data, screenshots, conversation content, runtime logs, raw environment snapshots, SDK archives, application packages, and machine-bound binaries.

The upstream Weston copyright and license notice is retained in [LICENSE.weston](LICENSE.weston).
