# WSLg trusted native IME bridge and development fixtures

These sources implement the pinned integration recorded in
[`docs/IME.md`](../../docs/IME.md).
The protocol tools do not deploy themselves or modify applications. The
explicit `install_user_session.py` and `activate_candidate.ps1` commands stage
the local candidate and reversible launch settings. Current deployment and
acceptance limits are in the
[production record](../../docs/IME_PRODUCTION.md).

The broker handles one trusted connection per process. The
`session_supervisor.py` couples its lifetime to Fcitx; systemd restarts both
after either exits, avoiding reuse of an old Wayland protocol stream.

The intended path is:

```text
Weston-launched helper (trusted WAYLAND_SOCKET)
  -> SCM_RIGHTS over private shared Linux Unix socket
  -> Ubuntu broker
  -> session DBus OpenWaylandConnectionSocket
  -> Fcitx native Wayland frontend
```

The socket's parent must be a real directory owned by the same UID
with mode 0700. The helper/supervisor can create it if missing. The broker
creates a mode-0600 SOCK_SEQPACKET socket and both
ends check SO_PEERCRED. Do not place this control socket on DrvFS or in an
unprotected directory. The helper only works with a compositor-inherited
WAYLAND_SOCKET. Do not remove Weston's input-method authorization check.

For experiments, isolate **all** of the session bus, XDG_CONFIG_HOME,
XDG_DATA_HOME and XDG_CACHE_HOME before starting a test daemon. The option to
enable the addon without a default untrusted display connection is:

```text
fcitx5 --option=wayland=nodefault
```

This is only the option syntax; actual test startup also needs the necessary
addons and a private bus. It is not a command to replace the user's daemon.
The 5.1.7 `-k` short option is absent from its getopt string despite the help
text; the experiments use the supported long form `--keep`.

To build an isolated protocol fixture inside Ubuntu, first create a fresh
output directory and export **the current system distro's**
`/usr/lib/weston/libexec_weston.so.0` to that directory. Then run:

```bash
python3 tools/ime/build_protocol_fixture.py --output /absolute/fresh/output
WSLG_IME_RELAY_BIN=/absolute/fresh/output/trusted-socket-relay \
  python3 -m unittest discover -s tests -p test_ime_trusted_socket.py -v
```

The builder uses the project's pinned source and existing exported SDK,
refuses to overwrite artifacts and does not install anything. Before running
modules in the system distro, check dependencies using its actual loader.
For the fixture shell, `libexec_weston.so.0` is in `/usr/lib/weston`; a scoped
`LD_LIBRARY_PATH=/usr/lib/weston` can be used for **the ldd preflight only**.
The Weston process already loads that same stock frontend library.

`protocol_probe_shell.c` supports test-only synthesized pinyin keys when
`WSLG_IME_PROBE_KEYS=1` is explicitly set. It must never be mapped as the live
WSLg shell. `protocol_text_client.c` receives and records native v1 events.
These noop/headless protocol fixtures are deliberately distinct from GPU +
Wayland original-application desktop acceptance. No fixture binary belongs
in the production module map.

With `--source /fresh/patched/source --panels`, the fixture also compiles the
new input-panel implementation and enables lifecycle assertions. Its RAIL
transport is a mock: passing proves local view mapping and cleanup, not
Windows candidate visibility, host activation policy or actual minimize
behavior. Synthesized keys remain confined to the fixture's own seat.

`build_candidate.py` builds the complete RDP backend and RAIL shell against
the pinned SDK, keeps the accepted desktop-library dependency, checks the
GLIBC ceiling and emits stripped candidate binaries. Use a fresh output;
never rebuild a module that may be mapped by the running compositor.

The user reported the deployed IME candidate successful. Multiple outputs,
scales, GTK/X11 regressions, every internal minimize path and long-duration
stability were not individually reported. D3D12 was observed in the original
app; Chromium hardware window compositing remains unverified after its
earlier software result.

`prepare_production.py` promotes verified code into a fresh self-contained
runtime. `activate_production.ps1` checks the real system loader, backs up
settings, upgrades only files matching the previous private manifest and
optionally restarts WSL. Production Fcitx uses warning-level logs and disables
key tracing. The ordinary application wrapper clears prior diagnostics and
retains only Wayland/IME selection flags. See the production record above.

Run reversible-installer tests without touching the actual session:

```bash
python3 -m unittest discover -s tests -p test_ime_production.py -v
```
