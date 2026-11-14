param(
    [string]$Distribution = 'Ubuntu',
    [string]$Candidate = 'wslg-1.0.79-ime-candidate-20261114-b',
    [string]$Production = 'wslg-1.0.79-ime-production-20261114',
    [Parameter(Mandatory = $true)][string]$UpgradeFrom,
    [switch]$RestartWsl
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$versions = (& wsl --system --exec cat /mnt/wslg/versions.txt) -join "`n"
if ($LASTEXITCODE -ne 0 -or $versions -notmatch '(?m)^WSLg: 1\.0\.79\s*$' -or
    $versions -notmatch 'weston:\s+a7e35fdab455dce5774b43b8aff682f748307e31') {
    throw 'Production modules are pinned to WSLg 1.0.79 and the recorded Weston commit.'
}
foreach ($label in @($Candidate,$Production)) {
    if ($label -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw 'Use simple runtime directory names.' }
}
$linuxRoot = (& wsl -d $Distribution --cd $root --exec pwd).Trim()
if ($LASTEXITCODE -ne 0 -or !$linuxRoot.StartsWith('/')) { throw 'Cannot resolve Ubuntu workspace.' }
$source = "$linuxRoot/runtime/$Candidate"
$destination = "$linuxRoot/runtime/$Production"
$configPath = Join-Path $env:USERPROFILE '.wslgconfig'
$before = [IO.File]::ReadAllText($configPath)
if (([regex]::Matches($before,[regex]::Escape($source+'/'))).Count -ne 3 -or
    !$before.Contains("XDG_CONFIG_HOME=$source/config") -or
    !$before.Contains("WESTON_MODULE_MAP=rdp-backend.so=$source/rdp-backend.so;rdprail-shell.so=$source/rdprail-shell.so")) {
    throw 'Current WSLg map is not the expected accepted candidate; inspect before promotion.'
}
foreach ($entry in @('WESTON_RDP_DEBUG_LEVEL=2','WESTON_RDPRAIL_SHELL_DEBUG_LEVEL=2',
                    'WESTON_RDP_DEBUG_CLIPBOARD_LEVEL=0')) {
    if (!$before.Contains($entry)) { throw 'Unexpected logging settings; inspect before promotion.' }
}
$private = Join-Path $root ('.state\ime-production-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $private | Out-Null
Copy-Item -LiteralPath $configPath -Destination (Join-Path $private 'wslgconfig.before')
$linuxBackup = "$linuxRoot/.state/" + (Split-Path $private -Leaf) + '/ubuntu'
& wsl -d $Distribution --cd $root --exec python3 tools/ime/prepare_production.py --source $source --destination $destination
if ($LASTEXITCODE -ne 0) { throw "Production preparation failed; no configuration changed. Backup: $private" }
foreach ($module in @('rdp-backend.so','rdprail-shell.so','libweston-desktop-9.so.0','trusted-socket-relay')) {
    $loader = (& wsl --system -u root --exec env LD_LIBRARY_PATH=/usr/lib/weston ldd -r "$destination/$module" 2>&1) -join "`n"
    $loader | Set-Content -LiteralPath (Join-Path $private ($module+'.loader.log')) -Encoding UTF8
    if ($LASTEXITCODE -ne 0 -or $loader -match 'not found|undefined symbol') {
        throw "System-distro loader preflight failed for $module; no configuration changed."
    }
}
$runtime = Join-Path $root "runtime\$Production"
$utf8 = New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Path (Join-Path $runtime 'config') | Out-Null
[IO.File]::WriteAllText((Join-Path $runtime 'config\weston.ini'),
    "[xwayland]`ndisable_access_control=true`n`n[input-method]`npath=$destination/trusted-socket-relay`n",$utf8)
& wsl -d $Distribution --cd $root --exec python3 tools/ime/install_user_session.py --runtime $destination --backup $linuxBackup --upgrade-from $UpgradeFrom --remove-legacy-libva
if ($LASTEXITCODE -ne 0) { throw "User staging failed; inspect the private per-file manifest before retrying: $private" }
$after = $before.Replace($source+'/',$destination+'/')
if ([IO.File]::ReadAllText($configPath) -ne $before) { throw 'WSLg config changed during staging; inspect before applying.' }
[IO.File]::WriteAllText($configPath,$after,$utf8)
$state = @{ root=$root; distribution=$Distribution; config_path=$configPath;
    linux_backup="$linuxBackup/manifest.json"; production=$Production;
    installed_config_sha256=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash }
[IO.File]::WriteAllText((Join-Path $private 'activation.json'),($state | ConvertTo-Json),$utf8)
$rollback = @'
$ErrorActionPreference = 'Stop'
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'activation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $state.config_path -Algorithm SHA256).Hash -ne $state.installed_config_sha256) {
    throw 'WSLg configuration changed after production activation; inspect before restoring.'
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'wslgconfig.before') -Destination $state.config_path -Force
& wsl --shutdown
if ($LASTEXITCODE -ne 0) { throw 'Cannot stop WSL for rollback.' }
& wsl -d $state.distribution --cd $state.root --exec python3 tools/ime/install_user_session.py --rollback $state.linux_backup
if ($LASTEXITCODE -ne 0) { throw 'User settings changed after deployment; inspect the private manifest.' }
& wsl --shutdown
& wsl -d $state.distribution --exec zsh -lc true
Write-Output 'Restored the accepted IME candidate configuration.'
'@
[IO.File]::WriteAllText((Join-Path $private 'rollback.ps1'),$rollback,$utf8)
Write-Output "Production staged. Private rollback: $private\rollback.ps1"
if ($RestartWsl) {
    & wsl --shutdown
    if ($LASTEXITCODE -ne 0) { throw 'WSL shutdown failed; inspect the private rollback.' }
    & wsl -d $Distribution --exec zsh -lc true
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu startup failed; inspect the private rollback.' }
    Write-Output 'Production restarted. Verify live module maps and the trusted IME handoff.'
}
