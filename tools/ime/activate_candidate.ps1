param(
    [string]$Distribution = 'Ubuntu',
    [string]$Candidate = 'wslg-1.0.79-ime-candidate-20261114-b',
    [switch]$RestartWsl
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $root "runtime\$Candidate"
if (!(Test-Path -LiteralPath (Join-Path $runtime 'build.json'))) {
    throw 'Candidate build manifest missing.'
}
$wslVersion = (& wsl --system --exec cat /mnt/wslg/versions.txt) -join "`n"
if ($wslVersion -notmatch '(?m)^WSLg: 1\.0\.79\s*$' -or
    $wslVersion -notmatch 'weston:\s+a7e35fdab455dce5774b43b8aff682f748307e31') {
    throw 'This candidate is pinned to WSLg 1.0.79; inspect the installed version first.'
}
$linuxRoot = (& wsl -d $Distribution --cd $root --exec pwd).Trim()
if ($LASTEXITCODE -ne 0 -or !$linuxRoot.StartsWith('/')) { throw 'Cannot resolve Ubuntu workspace.' }
$linuxRuntime = "$linuxRoot/runtime/$Candidate"
$private = Join-Path $root ('.state\ime-activation-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $private | Out-Null
$configPath = Join-Path $env:USERPROFILE '.wslgconfig'
$config = [IO.File]::ReadAllText($configPath)
if ($config -notmatch '(?m)^\[system-distro-env\]\s*$' -or
    $config -match '(?m)^XDG_CONFIG_HOME=' -or
    $config -match '(?m)^WSLG_IME_BRIDGE_SOCKET=') {
    throw 'Unexpected WSLg configuration; inspect it before changing the candidate.'
}
if (([regex]::Matches($config, '(?m)^WESTON_MODULE_MAP=.*$')).Count -ne 1) {
    throw 'Expected one existing WESTON_MODULE_MAP.'
}
Copy-Item -LiteralPath $configPath -Destination (Join-Path $private 'wslgconfig.before')
$utf8 = New-Object System.Text.UTF8Encoding($false)
$configDir = Join-Path $runtime 'config'
New-Item -ItemType Directory -Path $configDir | Out-Null
$westonConfig = "[xwayland]`ndisable_access_control=true`n`n[input-method]`npath=$linuxRuntime/trusted-socket-relay`n"
[IO.File]::WriteAllText((Join-Path $configDir 'weston.ini'), $westonConfig, $utf8)
$linuxBackup = "$linuxRoot/" + ((Split-Path $private -Leaf) -replace '^', '.state/') + '/ubuntu'
$stage = & wsl -d $Distribution --cd $root --exec python3 tools/ime/install_user_session.py --runtime $linuxRuntime --backup $linuxBackup
if ($LASTEXITCODE -ne 0) { throw "Ubuntu staging failed. Backup: $private" }
$stage | Set-Content -Encoding UTF8 (Join-Path $private 'ubuntu-staging.json')
$moduleMap = "WESTON_MODULE_MAP=rdp-backend.so=$linuxRuntime/rdp-backend.so;rdprail-shell.so=$linuxRuntime/rdprail-shell.so"
$updated = [regex]::Replace($config, '(?m)^WESTON_MODULE_MAP=.*$', $moduleMap)
$updated = [regex]::Replace($updated, '(?m)^\[system-distro-env\]\s*$',
    "[system-distro-env]`nXDG_CONFIG_HOME=$linuxRuntime/config`nWSLG_IME_BRIDGE_SOCKET=/mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock")
[IO.File]::WriteAllText($configPath, $updated, $utf8)
$manifest = @{
    root = $root; distribution = $Distribution; config_path = $configPath;
    linux_backup = "$linuxBackup/manifest.json"; candidate = $Candidate
}
$manifest | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $private 'activation.json')
$rollback = @'
$ErrorActionPreference = 'Stop'
$state = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'activation.json') | ConvertFrom-Json
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'wslgconfig.before') -Destination $state.config_path -Force
& wsl --shutdown
& wsl -d $state.distribution --cd $state.root --exec python3 tools/ime/install_user_session.py --rollback $state.linux_backup
if ($LASTEXITCODE -ne 0) { throw 'Ubuntu settings were modified after activation; inspect the backup manifest.' }
& wsl --shutdown
& wsl -d $state.distribution --exec zsh -lc true
Write-Output 'Restored the previous compositor map and Ubuntu launch settings.'
'@
[IO.File]::WriteAllText((Join-Path $private 'rollback.ps1'), $rollback, $utf8)
Write-Output "Candidate staged. Rollback: $private\rollback.ps1"
if ($RestartWsl) {
    & wsl --shutdown
    if ($LASTEXITCODE -ne 0) { throw 'WSL shutdown failed.' }
    & wsl -d $Distribution --exec /usr/bin/true
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu restart failed; use rollback.ps1.' }
    Write-Output 'WSL restarted. Verify actual compositor maps and the user service before acceptance.'
}
