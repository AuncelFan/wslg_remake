# Fcitx 5.1.7 native Wayland shortcut backport

This is a narrow backport for the Ubuntu 24.04 Fcitx 5.1.7-1build3 deployment.
The actual behavior change is one request in `modifiersCallback()`:

```cpp
ic_->modifiers(serial_, mods_depressed, mods_latched, mods_locked, group);
```

Upstream 5.1.13 contains this request; 5.1.7 does not. The original desktop
reproduction showed unconsumed `c` and `z` reaching `wl_keyboard` without the
Ctrl modifier while the v1 input-method grab was active. The backport retains
the modifier event ordering supplied to Fcitx, instead of guessing the current
keyboard state later in Weston.

## Build inside the actual Ubuntu user distro

The project is source only. No application files, system Weston modules or
package-owned Fcitx libraries are replaced by the following build commands.
Build dependencies installed for the local investigation were:

```sh
sudo apt-get install --no-install-recommends \
  cmake extra-cmake-modules libfcitx5core-dev libfcitx5config-dev libfcitx5utils-dev
```

The compiler, `libwayland-dev`, `libxkbcommon-dev`, Wayland protocols, `curl`,
`patch` and binutils were already available. These are also required.
Use a fresh source and build directory; `REPO` is the repository root:

```sh
REPO="$PWD"
TASK_BUILD="$HOME/.cache/wslg-fcitx-shortcuts-build"
mkdir -p "$TASK_BUILD"
cd "$TASK_BUILD"
curl -fL --retry 3 -o fcitx5-5.1.7.tar.gz \
  https://codeload.github.com/fcitx/fcitx5/tar.gz/refs/tags/5.1.7
printf '%s  %s\n' \
  01f76b523401e877da21766eb2c72605bc098e5f738474dd66beb6e4f8678a5a \
  fcitx5-5.1.7.tar.gz | sha256sum -c -
tar xzf fcitx5-5.1.7.tar.gz
patch --batch --fuzz=0 -d fcitx5-5.1.7 -p1 \
  < "$REPO/patches/fcitx5/0001-waylandim-v1-forward-modifiers.patch"
cmake -S "$REPO/tools/ime/fcitx-waylandim" -B build \
  -DFCITX_SOURCE="$TASK_BUILD/fcitx5-5.1.7" -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 6 --target waylandim
```

`libwaylandim.so` is built against the installed Fcitx core/config/utils.
Private Wayland protocol wrappers come from the same 5.1.7 source. It does not
build or install another Fcitx daemon. The custom CMake file mirrors upstream
hidden visibility and checks for undefined link symbols. The small `config.h`
only supplies feature defines needed by private inline utility headers.

## Scoped deployment

The tested local deployment uses a fresh user-owned directory:

```text
~/.local/lib/wslg-ime/fcitx5-5.1.7-shortcuts-20261116/
  libwaylandim.so
  guarded_session.py
  manifest.json
```

Copy the finished module into that directory and strip the **copy** with
`strip --strip-unneeded`; never rebuild a module currently mapped by a process.
Check the copy with `ldd -r` and `readelf -SW`. Generate `manifest.json` from
the installed deployment, using actual values:

```json
{
  "packages": {
    "fcitx5": "5.1.7-1build3",
    "fcitx5-modules:amd64": "5.1.7-1build3",
    "libfcitx5config6:amd64": "5.1.7-1build3",
    "libfcitx5core7:amd64": "5.1.7-1build3",
    "libfcitx5utils2:amd64": "5.1.7-1build3"
  },
  "sha256": "<SHA-256 of the stripped local module>",
  "system_addon_dir": "/usr/lib/x86_64-linux-gnu/fcitx5"
}
```

The guard sets `FCITX_ADDON_DIRS` **only for this managed session** and only
when package versions and the module checksum match. It does not export the
variable in `.zshenv` or alter all Fcitx processes. On a mismatch it logs a
warning and runs with system addons. That fallback preserves startup, but the
shortcut fix then depends on the newly installed system Fcitx version.

The local user-unit drop-in is
`~/.config/systemd/user/wslg-ime.service.d/20-shortcut-modifiers.conf`:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 "<ADDON>/guarded_session.py" --addon-dir "<ADDON>" -- /usr/bin/python3 "<RUNTIME>/ime/session_supervisor.py" --socket /mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock
```

Replace `<ADDON>` and `<RUNTIME>` with real absolute paths. Preserve the
previously accepted supervisor command and any local unit arguments. The
original service file and supervisor snapshot remain unchanged. Activate with:

```sh
systemctl --user daemon-reload
systemctl --user restart wslg-ime.service
```

Check the actual Fcitx process maps, not just the unit environment. The
supervisor acquires the trusted compositor connection as before. Warning-level
logs and `key_trace=0` remain in use.

## Rollback and updates

Remove only this drop-in, leaving all other unit customization intact:

```sh
rm -- "$HOME/.config/systemd/user/wslg-ime.service.d/20-shortcut-modifiers.conf"
systemctl --user daemon-reload
systemctl --user restart wslg-ime.service
```

This restores the original system addon and can reintroduce the shortcut bug
on 5.1.7. No WSL shutdown is needed. Keep the addon directory until the process
has stopped using it. After any package upgrade, check the guard's warning,
actual loaded module, Ctrl shortcuts and Chinese input; do not edit the
manifest merely to force an incompatible module to load.

## Verification on 2026-11-16

- A live WSLg native Wayland diagnostic client received Ctrl+C and Ctrl+Z with
  `ctrl=true` without activating text-input-v1, and `ctrl=false` with the
  original Fcitx 5.1.7 v1 route.
- With the backport enabled, the same v1 route received Ctrl+C, Ctrl+Z,
  Ctrl+A and Ctrl+Shift+Z with correct modifier masks and release resets.
- With Pinyin active, the client committed the expected fixed text “你好”,
  then received Ctrl+C/Z/A/X/V with Ctrl set. Only allowlisted keys, modifier
  masks and a boolean comparison for this fixed text were logged.
- The service was active with zero automatic restarts. Its maps selected the
  user-local addon. The package-owned module hash was unchanged.
- These client tests used SHM to isolate **keyboard behavior**; they are not
  GPU rendering acceptance. The original application, D3D12 selection,
  wrapper and accepted compositor configuration were unchanged.
- Automated ChatGPT copy/undo acceptance was not completed because Windows
  foreground activation did not succeed. Subsequent user feedback confirmed
  Ctrl+C and other Ctrl shortcuts work. This feedback is separate from the
  protocol-client evidence above, not an automated app acceptance result.

Ctrl+Space can also be reserved by the host Windows IME. In the reported
environment, a read-only Windows IME hotkey query confirmed that assignment;
the user reported switching the Fcitx trigger to Ctrl+Shift worked. No Windows
hotkey setting was changed, and actual host interception was not separately
instrumented. The Fcitx modifier fix cannot forward keys consumed on the host.

The reference stripped Release module was 651,680 bytes (about 636 KiB).
Generate a checksum for your own finished build when creating its manifest.
This is a custom backport, not an official Fcitx release binary. Local logs,
screenshots, manifests and binaries are not source publication material.

Primary source references:

- <https://github.com/fcitx/fcitx5/blob/5.1.7/src/frontend/waylandim/waylandimserver.cpp>
- <https://github.com/fcitx/fcitx5/blob/5.1.13/src/frontend/waylandim/waylandimserver.cpp>
- <https://github.com/fcitx/fcitx5/blob/5.1.7/src/lib/fcitx-utils/standardpath.cpp>

An exact upstream fixing commit was not established; the release sources
above, rather than a guessed commit ID, are the recorded provenance.
