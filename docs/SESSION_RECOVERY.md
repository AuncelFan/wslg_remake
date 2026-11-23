# WSLg clipboard, input and session recovery

On the tested WSLg 1.0.79 configuration, a Windows-to-WSL clipboard request
overlapped an active transfer. Weston aborted inside
`clipboard_data_source_write()` at `source->data_source_fd == fd`. WSLGd
started a new Weston. The original Wayland windows lost their connection,
and a new IME relay timed out waiting for the broker. The broker and Fcitx
remained running with no trusted connection to the new compositor.

[Weston patch 0005](../patches/weston/0005-rdpclip-preserve-active-transfer-fd.patch)
keeps the descriptor registered with the active write event and closes the
descriptor for the overlapping request. That requester gets EOF and can
retry. The change touches `rdpclip.c` and keeps the descriptor consistency
assertion. The upstream failure and the fd ownership rule are documented
in [WSLg #1407](https://github.com/microsoft/wslg/issues/1407) and
[weston-mirror #166](https://github.com/microsoft/weston-mirror/pull/166).

The new relay monitors the Weston parent with a Linux pidfd and closes its
control connection when Weston exits. Fcitx owns the handed-off Wayland
stream. The broker accepts one relay and closes its listener so a replacement
relay waits for the next broker. The supervisor waits for both the broker's
handoff and a native Fcitx Wayland input context before reporting `READY=1`.
It checks the relay heartbeat and Fcitx context during the session, and the
existing user service restarts the inputs together after failure. Systemd
also restarts an unresponsive supervisor after a watchdog timeout.

An independent quick-relaunch failure occurred while the original
application was shutting down. A new invocation connected to the old
Chromium `SingletonSocket` and exited successfully. The old process then
finished quitting. The [launcher](../tools/ime/chatgpt_wayland_wrapper.sh)
retries an argument-free launch once if the matching old process exits in
the 10-second observation window. Launches with explicit arguments keep
their ordinary application behavior. Deliberately quitting the old window
immediately after such an argument-free handoff can also trigger the retry.

## Build and update an existing deployment

Use the pinned Weston source and matching WSLg SDK in [BUILD.md](BUILD.md).
Apply patches 0001–0005 in order to a fresh tree. The existing
`tools/ime/build_candidate.py` produces both the backend and relay in a
fresh runtime. Use the actual WSLg system-distro loader for `ldd -r` on
both outputs before mapping them. Choose a persistent directory visible
to both the system distro and Ubuntu.

Back up `.wslgconfig`, `weston.ini`, the IME user unit and drop-ins,
and the user launcher. Record the original paths and installed hashes
privately. Coordinate these changes before restarting WSL:

1. Set the `rdp-backend.so` entry of `WESTON_MODULE_MAP` to the new
   backend in Windows `.wslgconfig`. Keep the existing shell entry and its
   matching desktop library together.
2. Set `[input-method]` `path=` in the selected `weston.ini` to the new
   `trusted-socket-relay`. Keep the existing `WSLG_IME_BRIDGE_SOCKET`
   and private socket directory.
3. Copy `tools/ime/session_supervisor.py` and
   `tools/ime/trusted_socket_broker.py` next to each other under the
   new runtime's `ime/` directory. Change the effective `ExecStart`
   to the new supervisor path and keep the same `--socket` argument.
   If the Fcitx shortcut guard supplies `ExecStart`, update the
   supervisor path in that drop-in, keeping the guard and its arguments.
4. Add the following to `wslg-ime.service.d/30-recovery-policy.conf`
   under the user's systemd configuration. For fresh installations,
   `install_user_session.py` emits the equivalent policy.

   ```ini
   [Unit]
   StartLimitIntervalSec=0

   [Service]
   Type=notify
   NotifyAccess=main
   Restart=on-failure
   RestartSec=5s
   TimeoutStartSec=55s
   WatchdogSec=25s
   ```

5. Merge the launcher changes into the existing user wrapper. Preserve
   site-specific settings and the desktop entry that calls the wrapper.
   The original application still starts with native Wayland, text input
   v1 and Mesa D3D12.

For deployments that use the [GTK portal seat guard](PORTAL_SEAT_READY.md),
add `Restart=on-failure` under `[Service]` in user drop-ins for
`xdg-desktop-portal.service` and `xdg-desktop-portal-gtk.service`. The tested
restart delays were `5s` for the frontend and `3s` for the GTK backend.
The GTK backend runs its existing `ExecStartPre` after a restart.
Use `systemd-analyze --user verify` on the affected units.

After saving work in WSL, reload the user manager and perform a full
WSL restart to load the configured modules together. Check the live Weston
module mappings and the path of its relay. Check the IME service with:

```bash
systemctl --user show wslg-ime.service -p ActiveState -p SubState -p StatusText
journalctl --user -u wslg-ime.service -b -n 40 --no-pager
```

Successful startup shows `StatusText=Fcitx connected to Weston` and a
`wayland-input-ready` event. Validate real Chinese input and the directory
chooser in the original application. The relay and Ubuntu scripts form a
matching set. An older relay has no heartbeat and will fail the new
supervisor's health check.

To roll back, use the private backups to restore the previous backend,
relay, supervisor, broker, user service policy and launcher as one set.
Check for subsequent edits before restoring the saved files. Restore the
previous portal policies if rolling back those changes too. Reload the
user manager, restart WSL to reload the module map, and repeat the input
check.

## Recorded verification

Tested with WSL 3.0.5.0, WSLg 1.0.79, Weston 9.0.0 at Microsoft commit
`a7e35fdab455dce5774b43b8aff682f748307e31`, MSRDC 1.2.7391, Ubuntu
Fcitx 5.1.7 and original ChatGPT 26.1106.51428.

- Two-way text clipboard transfer worked. During 20 consecutive paste
  actions, Weston logged two overlapping requests and kept running.
- Four immediate close-and-reopen trials ended with a new application
  process and a visible window after about 6–9 seconds.
- Separate exits of Fcitx, broker and relay recovered in about 6–7
  seconds. Stalls in Fcitx, broker and supervisor recovered in about
  22–30 seconds. The original Weston and application window survived
  these input-stack tests.
- The GTK backend and portal frontend each restarted after a controlled
  exit. After a controlled Weston exit, the new Weston, IME and GTK
  backend were ready in about seven seconds. Ubuntu kept the same boot.
- After reopening the original application, `Ctrl+Shift` switched to
  Pinyin and the test committed Chinese text. The directory chooser
  opened, browsed Home and cancelled through mouse interaction. The
  application used native Wayland and its GPU process loaded D3D12 and
  opened `/dev/dxg`. Hardware window compositing was not remeasured.

The lab checks cover the reproduced paths and a compositor-only restart.
A full WSL cold start, persistent configuration failures, compositor
hangs, and responsive components with broken protocol behavior remain
outside this verification. Fcitx context detection uses the 5.1.7
`DebugInfo` format. Review it when upgrading and repeat real input and
recovery checks.
