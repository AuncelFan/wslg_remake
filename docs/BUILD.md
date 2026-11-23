# Build and regression notes

The original minimize-only steps below remain the prerequisite baseline.
Native-IME additions are described at the end and in [IME.md](IME.md).

## Pinned inputs

The patches target Microsoft Weston commit:

```text
a7e35fdab455dce5774b43b8aff682f748307e31
```

The corresponding source archive is available from the Microsoft `weston-mirror` repository. Its SHA256 is:

```text
c70b47d0c5cb9150af36d4cceb412e619971fdb404d2432461cac3c7aa65078f
```

The FreeRDP/WinPR input must match the WSLg system distro, specifically FreeRDP commit `c4030980b29322a9cb2190711a5fadeeeb8b6a33` for the tested version. The SDK, original system binaries, and archives must be collected locally; they are not committed here.

## Prepare source

Run from the repository root in Ubuntu. These commands create local ignored files and do not modify the running compositor:

```bash
mkdir -p .cache .work evidence/desktop-state-20261112
commit=a7e35fdab455dce5774b43b8aff682f748307e31
archive=".cache/weston-$commit.tar.gz"
curl --fail --location "https://codeload.github.com/microsoft/weston-mirror/tar.gz/$commit" -o "$archive"
printf '%s  %s\n' c70b47d0c5cb9150af36d4cceb412e619971fdb404d2432461cac3c7aa65078f "$archive" | sha256sum --check
tar -xzf "$archive" -C .work
mv ".work/weston-mirror-$commit" .work/weston-a7e35fdab455
python3 tools/prepare_weston_candidate.py --destination .work/weston-reproduced
```

Use a fresh checkout/destination for preparation; do not overwrite an existing source directory. Stop if the SHA256 check fails. The preparation tool checks the fixed archive and patch before creating the RDP-patched source.

To prepare only the desktop candidate for the comparator replay:

```bash
mkdir -p .work/native-desktop-20261112/acked/source/libweston-desktop
cp .work/weston-a7e35fdab455/libweston-desktop/xdg-shell.c \
  .work/native-desktop-20261112/acked/source/libweston-desktop/xdg-shell.c
patch --batch --fuzz=0 -p1 \
  -d .work/native-desktop-20261112/acked/source \
  -i "$PWD/patches/weston/0002-xdg-shell-compare-last-acked-state.patch"
```

## Source-level regression

The required compiler and Wayland/Pixman development files must already be installed. These tests extract functions from the actual baseline/candidate sources; they do not operate a desktop or prove GPU acceptance.

```bash
python3 tools/test_weston_repaint.py \
  --candidate .work/weston-reproduced \
  --output evidence/repaint.json
python3 tools/test_weston_xdg_state.py
```

The RAIL harness contains 18 scenarios per variant, including deferred work, ACK coalescing, shutdown, multiple outputs/windows, and delayed ACKs. The comparator replay performs 330 assertions covering the captured activation failure, ACK-before-commit, queued configure states, geometry, and repeated independent-window transitions.

## Native component build tools

`build_native_rdp_backend.py` and `build_native_desktop.py` preserve the original tested build layout. Date suffixes identify that layout; they are not automatic version discovery.

The local layout required by these tools includes:

```text
.work/weston-a7e35fdab455/                    unmodified pinned source
.work/weston-reproduced/                     RDP patch applied
.work/native-weston-20261112/sdk/            matching headers and runtime libraries
.work/native-weston-20261112/system-sdk.tar
.work/native-weston-20261112/original-installed-rdp-backend.so
.work/native-weston-20261112/openssl-sdk/     matching OpenSSL headers
.work/weston-sdk/root/usr/include/libdrm/    DRM headers used by the build
.work/native-desktop-20261112/original/      local stock shell and desktop library
```

The desktop `original/` directory must contain `rdprail-shell.so` and `libweston-desktop-9.so.0` copied from the target WSLg system distro. The desktop builder generates baseline and patched libraries, then uses `patchelf` on shell copies to point to the respective libraries.

No full SDK export/bootstrap tool is included. Review both builders, obtain the matching local SDK inputs, and use new output/evidence directories. The RDP builder has no existing-output protection: never run its defaults over a library currently loaded by Weston. The desktop builder refuses existing libraries/build reports, but still references the pinned SDK and original-library locations.

The build uses `-O2 -g -fPIC` and links with `--no-undefined` and `-z now`. Validate GLIBC requirements against the WSLg **system distro**, not just Ubuntu. The tested backend and shell require at most GLIBC 2.38; the rebuilt desktop library requires at most GLIBC 2.4.

## Deployment and rollback

The PowerShell scripts operate on the current Windows user's `.wslgconfig` and may terminate/restart Ubuntu when `-RestartUbuntu` is supplied. Save work before invoking them. They do not rebuild missing binaries.

`set_native_weston.ps1` selects the RDP variant. `set_native_desktop.ps1` selects a shell copy bound to its desktop library. Review the current configuration, preserve unrelated mappings, and inspect the resulting Weston process maps; the configuration text alone does not prove the candidate was loaded.

The stock rollback restores the entire saved pre-experiment `.wslgconfig`. Merge any later unrelated configuration changes before using it. Rollback selects the currently installed stock WSLg components; it does not downgrade WSL.

The generated shell contains a local absolute desktop-library dependency. Moving the repository requires regenerating the shell copy and updating module mappings. Do not distribute that machine-bound artifact as a general binary release.

## Native-IME build extension

Use a fresh copy of the pinned source, with all three patches applied in order.
If working from a Windows-extracted CRLF tree, normalize C/header files to LF
only in this new copy before applying the patches; preserve original inputs
and account for normalization separately from functional changes.

The candidate builder additionally requires a private SDK directory containing
`system-shell-sdk.tar`, exported from the actual target system distro with its
`usr/lib` layout. It must include the matching libexec frontend and the shell's
GLib/WinPR/librsvg/PNG/JPEG/WebP dependencies. Local development headers and
`pkg-config` packages are also required. No SDK is bundled or auto-downloaded.

The accepted minimize-patched desktop library must be present at
`runtime/wslg-1.0.79-weston-a7e35fd-production/libweston-desktop-9.so.0`.
This is a local prerequisite, not a committed file.

```bash
python3 tools/ime/build_candidate.py \
  --source /absolute/fresh/all-three-patches-source \
  --output runtime/wslg-1.0.79-ime-candidate-20261114-b \
  --extra-sdk /absolute/private/system-shell-sdk-directory
python3 -m unittest discover -s tests -p test_ime_production.py -v
WSLG_IME_RELAY_BIN="$PWD/runtime/wslg-1.0.79-ime-candidate-20261114-b/trusted-socket-relay" \
  python3 -m unittest discover -s tests -p test_ime_trusted_socket.py -v
```

Outputs must be new. The builder uses `-O2 -g`, retains local separate debug
files, and emits stripped runtime artifacts. Before deployment, check real
system-distro loading, preserve existing module mappings and private backups,
and verify original-application GPU/Wayland and physical input separately.

`activate_candidate.ps1 -RestartWsl` is a first-install developer tool for the
recorded old Fcitx startup block. It refuses existing user units or unexpected
configuration. After acceptance, `activate_production.ps1` upgrades from its
private manifest and relocates the shell dependency into one fresh production
runtime. See [promotion and rollback](IME_PRODUCTION.md).

The isolated protocol fixture and mock RAIL tests in `tools/ime/` must never
replace the live WSLg shell or be counted as real application GPU/GUI tests.

## Cursor alignment extension

Apply patch 0004 after patches 0001-0003 to a fresh pinned source tree. Historical
patch 0001 contains mixed line endings: normalize both temporary source files
and temporary patch copies to LF before applying the complete series, and use
`patch --fuzz=0`. Keep the original archive and accepted patch inputs unchanged.
The [pointer record](POINTER_ALIGNMENT.md) explains the reproduced failure,
measured results, scope and deployment map.

```bash
WESTON_CURSOR_SOURCE=/absolute/fresh/all-four-patches-source \
  python3 -m unittest discover -s tests -p test_weston_cursor.py -v
```

The test extracts the actual cursor update function and executes eight geometry
and update scenarios. It is separate from the native Wayland/D3D12 integration
probe, whose build and physical cross-output test procedure are included in the
pointer record. Compile the probe in a scratch directory; generated protocol
files and test binaries are local artifacts.

The existing `tools/ime/build_candidate.py` accepts the patched source
and matching SDK. Use a fresh output directory. For this backend-only change,
retain the accepted IME shell, its desktop library and helper rather than mapping
newly built unused components. Check the actual system-distro loader and live
Weston mappings before accepting the changed backend. Rebuilds, deployment and
WSL restarts are explicit local operations, not effects of applying the patch.

## Clipboard and session recovery extension

Apply patch 0005 after patches 0001–0004 for the recovery build. Use the same
pinned SDK with `tools/ime/build_candidate.py` and a fresh output directory to
produce the new RDP backend and relay. For an existing deployment, follow
the [recovery guide](SESSION_RECOVERY.md) to select these outputs and update
the matching Ubuntu user-service scripts.
