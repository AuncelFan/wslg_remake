# Maintenance after WSL updates

The accepted baseline targets WSL 3.0.5.0 / WSLg 1.0.79, Weston 9.0.0 commit `a7e35fdab455dce5774b43b8aff682f748307e31`, and FreeRDP commit `c4030980b29322a9cb2190711a5fadeeeb8b6a33`. The minimize patches modify four files (+83 / -3); the native-IME patch modifies another five-file set (+557 / -171), with eight distinct source files overall. See [IME implementation](IME.md) and [current production configuration](IME_PRODUCTION.md).

The 2026-11-16 [cursor alignment extension](POINTER_ALIGNMENT.md) adds patch 0004
(+36 / -5) in two existing backend files; the distinct source-file count remains
eight. It changes only the RDP backend in the current local deployment. Preserve
the accepted IME shell/desktop combination and the separate Fcitx shortcut addon.

## Keep a private local baseline

Record the following locally before deployment and after a successful upgrade:

- `wsl.exe --version`, the distribution release and kernel version.
- The WSLg `/mnt/wslg/versions.txt` and system-distro release/glibc versions.
- SHA256 of installed Weston, its core library, RDP backend, desktop library, shell, FreeRDP/WinPR and loaded dependencies.
- SHA256 of candidate binaries, patches, source and SDK inputs; full build commands.
- Active configuration and actual Weston process mappings.
- The original application's package identity and integrity fingerprints.

Run system-distro inspection explicitly in the WSLg system distro, for example `wsl.exe --system -d Ubuntu -u root --exec ...`. Its `/usr/lib` is distinct from Ubuntu's `/usr/lib`.

Keep raw environment snapshots, logs and desktop evidence private. Do not commit user profiles, local filesystem paths, machine names, process environments, account data or screenshots to the public repository.

## Evaluate changes

1. Confirm the updated WSLg is actually running. A new WSL package version can coexist temporarily with an older running compositor session.
2. Verify that the expected candidates still exist and are actually mapped by Weston. Do not rely solely on `.wslgconfig` or `weston --version`.
3. If Weston or dependency fingerprints changed, review ABI and source changes even if the version string stayed the same.
4. Obtain the new matching source and SDK. Check whether upstream already fixed either issue before applying patches again.
5. Review the xdg-shell comparison, last-ACK state semantics, bufferless commit behavior, queue handling and geometry logic.
6. Review RAIL ACK callbacks, task threading, destruction/wait behavior, backpressure conditions and output lifetime.
7. Build into new directories; make the shell copy from the **new** stock shell. Check exported symbols, required symbols, SONAME/dependencies, GLIBC limits and actual process maps.
8. Repeat the same physical minimize/restore sequence and preserve a new private baseline. Do not overwrite the previous accepted baseline.

For the IME extension, also review input-panel roles, parent/output lifecycle,
RAIL popup ownership/no-activation, state-only hide delivery, and the separate
panel plugin API. Check trusted helper FD handoff, Fcitx protocol support and
the complete service lifecycle. Repeat native preedit, candidate selection,
commit/cancel, focus changes and minimize/restore with an active preedit.
Production shell source is rebuilt, and its relocated desktop dependency must
point to the matching production directory. Keep private per-file rollback
manifests; do not replace them with the historical whole-config stock rollback.

Successful `git apply --check` only establishes textual applicability. Matching fingerprints only establish absence of measured drift. Neither proves behavior or complete ABI compatibility.

## Preserve test behavior

Use the original application without injection or keepalive changes. Move the pointer onto the application's own minimize button, hover about 800 ms, click, then restore by physically clicking the taskbar (or the tray icon if that is the application's current behavior). Record which restoration path was used; do not merge different paths into one trial count. Verify content scrolling/input without dragging, resizing or maximizing as a recovery aid.

Test normal and maximized windows, longer hover, and short/long hidden intervals. Test other reachable application minimize entry points separately. Windows minimize shortcuts exercise a distinct path and are not a replacement for application-button tests.

## Pointer regression after updates

Review `rdp_rail_update_cursor()` against upstream changes to surface size,
buffer scale, client scale and RDP hotspot units. Recheck hotspot-only updates
and the RDP bitmap boundary rules. Run the function-level cursor harness and
repeat physical calibration on each output with cursor buffer scales 1 and 2.
Use the client's real Wayland move operation for cross-output checks: forcing
only the Windows HWND position can leave Weston input geometry unsynchronized.
Keep native Wayland and an observed D3D12 renderer in the acceptance path.

## GTK portal startup prerequisite

The 2026-11-18 [GTK portal follow-up](PORTAL_SEAT_READY.md) adds a one-shot
user-service prerequisite that waits for Wayland pointer/keyboard readiness.
It does not modify the Weston modules. After GTK, portal or WSLg updates,
review whether the late-seat initialization race still applies, inspect the
backend's display environment, and rerun the eight private-socket protocol
tests. Repeat a real cold start and the original application's complete
mouse-based directory selection; test RDP reconnect separately. Keep the
deployment receipt private for hash-checked rollback.

## Clipboard and session recovery

For patch 0005, check whether the updated RDP clipboard code already
preserves the active transfer descriptor during overlapping reads. Check
the Weston input-helper launch and respawn path, and deploy the relay and
Ubuntu IME scripts as a matching set. The Fcitx context check uses the
5.1.7 `DebugInfo` format. Confirm that real input resumes after a controlled
failure and after a full WSL start. Recheck the portal and the original
application's immediate close-and-relaunch path. Follow the
[recovery guide](SESSION_RECOVERY.md).

## Binary distribution note

The original tested artifacts were approximately 0.86 MiB (backend), 0.35 MiB (desktop library), and 0.15 MiB (shell copy), or 1.36 MiB combined. Size is not the reason this draft excludes them.

The compiled artifacts retain local build paths; the shell copy also has a machine-specific absolute dependency. A reusable binary release would require reproducible path sanitization, a relocatable deployment design, and fresh validation. The published repository contains source only. The local stripped production copies total approximately 381 KiB; see [production notes](PRODUCTION.md) for their custom-build classification and the low-log configuration.
