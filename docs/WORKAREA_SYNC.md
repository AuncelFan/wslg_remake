# Dynamic Windows work-area synchronization

## Diagnosis and accepted local behavior, 2026-11-18

The Windows RAIL window respected the taskbar, but Weston's cached work area
included the entire monitor. As a result, a maximized Wayland client received a
taller configure than the visible Windows window and its bottom was clipped.

This was reproduced with both the original ChatGPT installation and an
independent native Wayland/EGL/GLES client. The latter reported the renderer
`D3D12 (AMD Radeon 780M Graphics)`.

The observed difference was:

| Measurement | Before refresh | After refresh |
| --- | --- | --- |
| Windows monitor bounds | Current full monitor bounds | Unchanged |
| Windows work area / maximized client area | Correctly excludes the taskbar | Unchanged |
| Weston cached client work area | Incorrectly includes the taskbar | Matches Windows' current work area |
| Native Wayland maximize configure | Taller than the visible client area | Matches the work area after coordinate conversion |

Private diagnostic measurements and the actual monitor layout are omitted.
The implementation contains no monitor dimensions, taskbar height, fixed
primary-monitor origin, or precomputed Weston work area. Numeric layouts in
the test harness are synthetic fixtures, not deployment settings.

A read-only inspection of the running backend confirmed that its cached
primary client work area covered the full monitor. Re-sending Windows'
`WM_SETTINGCHANGE / SPI_SETWORKAREA` notification made MSRDC send fresh RAIL
`ClientSysparam` work areas for both monitors. Weston consumed them through its
existing `rail_client_ClientSysparam_callback` and
`shell_backend_set_desktop_workarea` path. Both monitors' caches then matched
their respective work areas, with the appropriate coordinate conversion.

The precise event that originally left the cache stale has not been captured.
Display-layout changes and reconnects appear in the preceding runtime history,
but the measurements do not establish which event caused the missed update.

## Production implementation

[`tools/windows/workarea_sync.cs`](../tools/windows/workarea_sync.cs) is a small
hidden Windows process. It:

1. Enumerates every current monitor with `EnumDisplayMonitors` and
   `GetMonitorInfo`, including `rcMonitor`, `rcWork`, and the primary flag. It
   reads effective monitor DPI under per-monitor DPI awareness.
2. Detects WSLg receivers using its native `_WSL` window-class markers. Ordinary
   Remote Desktop clients are excluded.
3. Observes work-area, monitor topology, scale, primary-display and WSLg
   connection changes with a one-second detection timer. It also registers for
   the current session's WTS events and handles display, settings, DPI and power
   notifications. A reconnect or unlock can request a refresh even when all
   monitor dimensions are unchanged.
4. Debounces changes for two seconds, then sends a bounded
   `WM_SETTINGCHANGE / SPI_SETWORKAREA` notification **only to WSLg's
   `TsWindow_GeneralWindowClass` receiver**. MSRDC reads the real work areas and
   supplies their coordinates through the existing RAIL channel.

The helper does not call `SystemParametersInfo(SPI_SETWORKAREA)` to change the
desktop. It does not resize or move application HWNDs, intercept keys, inspect
application content, start WSL, or alter taskbar settings. Signed monitor
coordinates and changing taskbar edges are preserved. Unchanged observations do
not produce a continuing stream of refreshes. Failed deliveries are retried.

This repair adds **no new Weston patch or replacement `.so`**. The existing
minimize, IME, Fcitx and cursor builds, `.wslgconfig`, application wrapper and
application installation remain the current baseline. Production Weston debug
levels were restored to 2 / 2, with clipboard tracing 0, after diagnosis.

## Installation and operation

The tested baseline is WSL 3.0.5.0 / WSLg 1.0.79 / MSRDC 1.2.7391 on
Windows 11 x64, with the existing native Wayland + D3D12 setup. The helper is a
Windows-side synchronization workaround; it is separate from the Weston
patches and does not require an application modification. Other client
versions need their own validation of the WSLg window-class detection.

Prerequisites: Windows PowerShell and the x64 .NET Framework C# compiler at
`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. The scripts compile
locally; no prebuilt executable, administrator access, Docker installation,
or additional compiler download is required on the tested system. WSLg and
the application's Wayland/GPU configuration must already be set up.

Run from Windows PowerShell in the source checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\test_workarea_sync.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\windows\install_workarea_sync.ps1
```

The first command runs the compiled logic checks without starting/stopping a
watcher or changing desktop settings. The second installs and starts it.

The installer compiles an optimized x64 GUI executable without PDB output using
the installed .NET Framework compiler. Each source hash gets its own version
directory under `%LOCALAPPDATA%\wslg_remake\workarea-sync`. It stops a previous
instance through a session-local named event and starts the new version hidden.

The current user's Startup folder receives `WSLg Work Area Sync.lnk`.
`-NoStartup` runs the installer without writing that shortcut; it does not remove
an existing shortcut. No administrator permission or scheduled system service is
required. The helper should remain running to repair future session and display
changes.

For an update, rerun the test and installation commands from the updated
checkout. The installer stops the existing helper in the current session and
starts the source-hash version. It refreshes the Startup shortcut unless
`-NoStartup` is supplied. Old version directories are retained; no mapped
Weston module or other application process is replaced.

Inspect local status:

```powershell
Get-Content "$env:LOCALAPPDATA\wslg_remake\workarea-sync\status.json" -Raw
Get-Process -Name wslg-workarea-sync
```

The status file contains current monitor geometry, refresh counts and delivery
state. It is local runtime evidence, not a public source artifact.

To send a single refresh without maintaining a watcher:

```powershell
$link = (New-Object -ComObject WScript.Shell).CreateShortcut(
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'WSLg Work Area Sync.lnk'))
Start-Process -FilePath $link.TargetPath -ArgumentList '--once' -WindowStyle Hidden -Wait
```

To disable this addition, stop it and remove only its startup shortcut:

```powershell
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'WSLg Work Area Sync.lnk'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($startup)
Start-Process -FilePath $link.TargetPath -ArgumentList '--stop' -WindowStyle Hidden -Wait
Remove-Item -LiteralPath $startup
```

No WSL restart is required for activation or removal. Removing the helper leaves
the last synchronized work areas in place until a later normal update.

## Validation scope

- Fifteen compiled logic checks passed: multiple remote resolutions, variable
  taskbar size, all taskbar edges, negative monitor origins, primary-monitor and
  DPI changes, RAIL connection changes, stable enumeration order, and exclusion
  of ordinary RDP receivers.
- Both current monitors' work areas were re-sent by MSRDC and verified in the
  running Weston backend and shell caches.
- A synthetic `WTS_REMOTE_CONNECT` notification to the helper's own hidden
  window caused a fresh delivery even with unchanged monitor geometry. The
  refresh count changed from one to two; it then remained stable while the
  display arrangement was unchanged.
- The original ChatGPT package passed `dpkg --verify chatgpt` with exit 0 and no
  output. It remained on native Wayland with the existing launch arguments; its
  GPU process had D3D12/DXCore libraries loaded. This alone is not a separate
  proof of Chromium hardware window composition.
- A physical mouse click on ChatGPT's own maximize control produced a window
  matching Windows' work area, with the bottom composer and send control
  completely visible. The native D3D12 probe's complete bottom border was also
  visible after its configure changed to the work-area height.
- The installed shortcut target and the single running helper were checked.
  A real remote disconnect/reconnect, logout/login, monitor hotplug or live DPI
  change was not performed during this session. Those remain real-session
  regression cases; synthetic notification tests are not reported as an
  actual RDP reconnection.

## Source-only distribution

The public repository contains the helper source, installer, regression tests,
and these deployment instructions. Executables/PDBs, Startup shortcuts,
screenshots, live status, process/memory inspections, local account paths,
and private diagnostic measurements are excluded. Installation paths are
derived from the installing user's Windows folders rather than an embedded
account or checkout path. Do not upload generated status files: they contain
the current monitor layout and process identifiers.
