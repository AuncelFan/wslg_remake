[CmdletBinding()]
param([switch]$NoStartup)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'workarea_sync.cs'
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
$installRoot = Join-Path $env:LOCALAPPDATA 'wslg_remake\workarea-sync'
$versionFolder = Join-Path $installRoot $hash.Substring(0,16)
$null = New-Item -ItemType Directory -Force -Path $versionFolder
$binary = Join-Path $versionFolder 'wslg-workarea-sync.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $binary)) {
    & $compiler /nologo /target:winexe /platform:x64 /optimize+ /debug- /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/out:$binary" $source
    if ($LASTEXITCODE -ne 0) { throw 'Work-area synchronizer compilation failed.' }
}
# Stop only this user's synchronizer through its session-local named event.
$stopping = Start-Process -FilePath $binary -ArgumentList '--stop' -WindowStyle Hidden -Wait -PassThru
if ($stopping.ExitCode -ne 0) { throw 'Could not stop the previous synchronizer.' }
$deadline = (Get-Date).AddSeconds(8)
do {
    $existing = @(Get-Process -Name 'wslg-workarea-sync' -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq [Diagnostics.Process]::GetCurrentProcess().SessionId })
    if ($existing.Count -eq 0) { break }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $deadline)
if ($existing.Count -gt 0) { throw 'Previous synchronizer has not exited; installation stopped.' }
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'WSLg Work Area Sync.lnk'
if (-not $NoStartup) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($startup)
    $shortcut.TargetPath = $binary
    $shortcut.Arguments = '--watch'
    $shortcut.WorkingDirectory = $versionFolder
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Refresh WSLg work areas after display and remote-session changes.'
    $shortcut.Save()
}
$process = Start-Process -FilePath $binary -ArgumentList '--watch' -WindowStyle Hidden -PassThru
@{binary=$binary;source_sha256=$hash;process_id=$process.Id;startup_enabled=(-not $NoStartup);startup_shortcut=$startup;status=(Join-Path $installRoot 'status.json')} | ConvertTo-Json
