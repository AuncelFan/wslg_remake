# GTK Wayland file chooser: wait for input before startup

Recorded on 2026-11-18. This follow-up addresses the reproduced file chooser
that could draw its window but ignored mouse and keyboard input. It adds a
one-shot prerequisite to the existing `xdg-desktop-portal-gtk.service` in
Ubuntu. It does not add a daemon or change ChatGPT, GTK, Fcitx or Weston
binaries. The existing native Wayland / D3D12 application configuration is
retained.

## Why the freeze returned

The original application's Create project → Add directory route opened a
GTK portal directory chooser. In the broken instance, even Home and Cancel
could not be clicked. Restarting the GTK backend had restored an earlier
instance on 2026-11-16, but had not established a startup ordering condition;
a later instance could enter the same state again.

A short read-only debugger inspection, followed by detach, found:

| State | Broken backend | Backend after recovery |
| --- | --- | --- |
| Display type | `GdkWaylandDisplay` | `GdkWaylandDisplay` |
| Wayland connection closed | No | No |
| Wayland error | 0 | 0 |
| GDK seats | 0 | 1 |
| Default GDK seat | `NULL` | Present |
| Default pointer / keyboard | Unavailable | Both present |
| Pending global-initialization closures | 1 | 0 |

The broken process already knew about `wl_seat`. Its initialization closure
remained queued even though the required `wl_compositor` and
`wl_data_device_manager` globals were present. This explains a drawable
window without usable input devices.

In the matching GTK 3.24.41 source,
`gdk_registry_handle_global()` queues seat initialization through
`postpone_on_globals_closure()`. The call to
`process_on_globals_closures()` is in `_gdk_wayland_display_open()`, after
the initial registry roundtrip; this file has no later call to drain that
queue when another global arrives. A seat arriving after that initialization
window can therefore remain pending. The local startup records also showed
the affected GTK backend starting before the RDP keyboard was ready.

Source provenance:

- [GNOME GTK 3.24.41, gdk/wayland/gdkdisplay-wayland.c](https://github.com/GNOME/gtk/blob/3.24.41/gdk/wayland/gdkdisplay-wayland.c)
- SHA256 of the inspected upstream source:
  `5ea9c1a872c80e9957a92cce5de1d2feec35ae12ec9ca89cda0be3ff8a29ccd2`.

This diagnosis combines the installed process's queue state, the matching
upstream source and the observed startup order. It is not a claim about all
GTK versions. The running local Weston already had
`enable_persistent_rail_seat=1`; the remaining race was GTK starting before
the first seat appeared. That persistent-seat setting was not changed in
this follow-up.

## Scope and behavior

[`wait_wayland_seat.c`](../tools/portal/wait_wayland_seat.c) connects to the
Wayland display, watches registry and seat-capability events, and exits
successfully when **one seat has both pointer and keyboard capabilities**.
It handles a delayed seat, delayed capabilities and seat removal/replacement
while waiting. It does not request `wl_pointer` or `wl_keyboard` objects,
read input events, create windows or stay running after readiness.

The standalone default timeout is 30 seconds. Installation uses a 20-second
monotonic deadline and a 25-second service startup timeout. There is no fixed
sleep when input is already ready. If input does not become ready, this
startup attempt fails instead of launching a GTK backend without input.
The guard exits 0 on readiness, 64 for invalid arguments, 69 if the display
connection is unavailable, 75 on timeout and nonzero for other failures.

[`install_seat_guard.py`](../tools/portal/install_seat_guard.py) compiles
with `-O2 -Wall -Wextra -Werror` and strips the result. The tested local
binary was 14,552 bytes with no `.debug_*` sections; that size is specific to
the local build. It is a custom-built tool, not an upstream release binary,
and is not included in this repository.

The installer preflights the guard using the systemd user manager's display
environment, then installs only a user-local binary and the scoped portal
drop-in. It refuses root, an existing receipt, an existing managed drop-in
or a mismatched binary in its source-hash-named directory. It runs
`daemon-reload` and `systemd-analyze --user verify`; it does not restart the
backend or WSL automatically.

## Install in the Ubuntu desktop session

Use the desktop user, with a working systemd user manager and the existing
GTK portal backend. Review other portal drop-ins first. Install build
dependencies if missing:

```bash
sudo apt install build-essential pkg-config libwayland-dev binutils python3
systemctl --user cat xdg-desktop-portal-gtk.service
```

Run from this repository. Keep the printed receipt path: it contains local
paths and the previous unit configuration and must remain private.

```bash
receipt="$HOME/.local/state/wslg-remake/portal-seat-$(date +%Y%m%dT%H%M%S)/deployment.json"
python3 tools/portal/install_seat_guard.py --install --receipt "$receipt"

# Save or close any outstanding chooser requests before restarting the backend.
systemctl --user restart xdg-desktop-portal-gtk.service
systemctl --user status xdg-desktop-portal-gtk.service
journalctl --user -u xdg-desktop-portal-gtk.service -b -n 30 --no-pager
```

The installed locations are:

```text
~/.local/lib/wslg-portal/<source-sha256-prefix>/wait-wayland-seat
~/.config/systemd/user/xdg-desktop-portal-gtk.service.d/60-wslg-seat-ready.conf
```

For the published guard source, the prefix is `1196c0a7e782ae53`. The drop-in
is equivalent to the following portable representation; the installer writes
a quoted absolute user-local path:

```ini
[Service]
Environment=GDK_BACKEND=wayland
UnsetEnvironment=WAYLAND_SOCKET
ExecStartPre="%h/.local/lib/wslg-portal/1196c0a7e782ae53/wait-wayland-seat" --timeout-ms=20000
TimeoutStartSec=25s
```

The existing service continues running normally. The prerequisite runs only
when that backend starts; it is not an ongoing health monitor. A failed
preflight or timeout needs inspection of display availability and input
readiness, rather than a switch to X11. Review journals locally before
sharing them because they can contain hostnames and paths.

## Rollback

After closing outstanding chooser requests, use the receipt printed during
installation. In a new shell, replace the value below with that actual
private path:

```bash
receipt='/absolute/private/path/to/deployment.json'
python3 tools/portal/install_seat_guard.py --rollback "$receipt"
systemctl --user restart xdg-desktop-portal-gtk.service
```

Rollback verifies every recorded file's SHA256 before removing files created
by this installation. It refuses changed files. A pre-existing identical
binary is retained. Other drop-ins and package-owned files are not managed
by this installer; the private receipt is retained for reference.

## Validation

The isolated protocol tests build a temporary compositor fixture and guard,
using a private socket that never connects to the desktop:

```bash
python3 -m unittest discover -s tests -p test_wayland_seat_guard.py -v
```

All eight tests passed: ready seat, late seat, delayed capabilities,
removed/replaced seat, connection loss, pointer-only timeout, no-seat
timeout and invalid timeout arguments. The fixture rejects requests for
actual keyboard/pointer objects. These are protocol tests, not GPU or
desktop acceptance tests.

The installed configuration also passed `systemd-analyze --user verify`.
Real mouse tests used the original application's project-directory chooser,
including browsing, Cancel, repeated opening and selecting a directory back
into the project form. Project creation was cancelled afterward.

One full `wsl --shutdown` / Ubuntu cold start confirmed that deployment
hashes persisted and exercised the early-start race:

| Monotonic seconds after boot | Event |
| --- | --- |
| 6.280977 | systemd began starting the GTK portal |
| 9.083450 | Guard reported pointer + keyboard ready and exited 0 |
| 9.404393 | GTK portal became active |

The prerequisite held the startup sequence for approximately **2.8 seconds**
in that real boot. Subsequent inspection found one GDK seat, both devices,
zero pending initialization closures and Wayland error 0. The production
application was relaunched with no diagnostic arguments, and the mouse
route Create project → Add directory → Home → Desktop → Open successfully
returned the directory to the form. The current portal invocation had zero
`GDK_IS_SEAT` / `GDK_IS_DEVICE` assertions. Some unrelated parent-window
and recent-file warnings remained.

Native Wayland and the existing D3D12 path were retained. A temporary
read-only GPU diagnostic reported an AMD Radeon 780M ANGLE/D3D12 renderer
with OpenGL and rasterization enabled, but the original application still
reported **`gpu_compositing=disabled_software`**, consistent with the
[previous production limitation](PRODUCTION.md). An independent native
Wayland/EGL hardware readback passed; it does not establish application
hardware window compositing. Diagnostic processes were closed before the
final ordinary-production-launch chooser test; no guard process remained.

This is a startup-order mitigation for the reproduced case. It does not
patch GTK's general late-global handling or guarantee arbitrary hotplug
behavior. RDP disconnect/reconnect stress testing was not performed in this
round.

## Version baseline and update checks

| Component | Tested version |
| --- | --- |
| WSL | 3.0.5.0 |
| Running kernel | 6.18.58.1-microsoft-standard-WSL2 |
| WSLg | 1.0.79 |
| MSRDC | 1.2.7391 |
| Windows | 10.0.26100.9457 |
| ChatGPT package | 26.1106.51428 |
| GTK 3 | 3.24.41-4ubuntu1.3 |
| xdg-desktop-portal | 1.18.4-1ubuntu2.24.04.3 |
| xdg-desktop-portal-gtk | 1.15.1-1build2 |
| Weston | 9.0.0, Microsoft commit `a7e35fdab455dce5774b43b8aff682f748307e31` |

Package integrity checks for the original application and GTK passed. The
existing production backend and shell hashes remained:

```text
rdp-backend.so:
38c4121ebbecb75f8a069e5886191d09278a85dde57b781036f2cc1a89f6e7ff
rdprail-shell.so:
6cfe07f2adb15c273d783898dcebb8494be36602359c0ef7f2d8a0ddba2e3e94
```

No `.wslgconfig`, application wrapper, Fcitx service or existing Weston
module was changed by this follow-up. Existing module compatibility checks
still apply; see [maintenance](MAINTENANCE.md).

After GTK, portal or WSLg updates, review the seat initialization path and
the backend's display environment, rerun the isolated tests, and repeat a
real cold start plus mouse-based directory browsing and selection. Review
RDP reconnect separately. If upstream removes the race, evaluate removing
this prerequisite with the recorded rollback procedure. Keep private
deployment receipts, boot identifiers, raw logs, debugger output,
screenshots and user data outside the public repository.
