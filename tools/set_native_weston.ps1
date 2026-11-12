param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('baseline','patched','stock')]
    [string]$Variant,
    [switch]$RestartUbuntu
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$evidenceDir = Join-Path $projectRoot 'evidence\native-wslg-20261112'
$configPath = Join-Path $env:USERPROFILE '.wslgconfig'
$backupPath = Join-Path $evidenceDir 'wslgconfig.before'
$backupState = Join-Path $evidenceDir 'config-backup.json'
$encoding = [System.Text.UTF8Encoding]::new($false)
New-Item -ItemType Directory -Force $evidenceDir | Out-Null

if (!(Test-Path -LiteralPath $backupState)) {
    $existed = Test-Path -LiteralPath $configPath
    if ($existed) { Copy-Item -LiteralPath $configPath -Destination $backupPath }
    @{config_path=$configPath; existed=$existed; saved_at=(Get-Date).ToString('o')} |
        ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $backupState
}

if ($Variant -eq 'stock') {
    $saved = Get-Content -Raw -LiteralPath $backupState | ConvertFrom-Json
    if ($saved.existed) { Copy-Item -LiteralPath $backupPath -Destination $configPath -Force }
    elseif (Test-Path -LiteralPath $configPath) { Remove-Item -LiteralPath $configPath }
} else {
    $moduleWindows = Join-Path $projectRoot ".work\native-weston-20261112\$Variant\rdp-backend.so"
    if (!(Test-Path -LiteralPath $moduleWindows)) { throw 'Build the module before changing configuration.' }
    $moduleLinux = '/mnt/' + $moduleWindows.Substring(0,1).ToLower() + $moduleWindows.Substring(2).Replace('\','/')
    $logWindows = Join-Path $evidenceDir "weston-$Variant.log"
    $logLinux = '/mnt/' + $logWindows.Substring(0,1).ToLower() + $logWindows.Substring(2).Replace('\','/')
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $configPath) {
        foreach ($line in [System.IO.File]::ReadAllLines($configPath)) { $lines.Add($line) }
    }
    $start = -1
    $end = $lines.Count
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[system-distro-env\]\s*$') { $start=$i; continue }
        if ($start -ge 0 -and $lines[$i] -match '^\s*\[') { $end=$i; break }
    }
    if ($start -lt 0) { $lines.Add('[system-distro-env]'); $start=$lines.Count-1; $end=$lines.Count }
    $updates = [ordered]@{
        WESTON_MODULE_MAP = "rdp-backend.so=$moduleLinux"
        WESTON_RDP_DEBUG_LEVEL = '5'
        WSLG_WESTON_LOG_PATH = $logLinux
    }
    for ($i = $start + 1; $i -lt $end; $i++) {
        if ($lines[$i] -match '^\s*WESTON_MODULE_MAP\s*=(.*)$') {
            $other = @($Matches[1].Split(';') | Where-Object { $_ -and $_ -notmatch '^rdp-backend\.so=' })
            if ($other.Count) { $updates.WESTON_MODULE_MAP = ($other + $updates.WESTON_MODULE_MAP) -join ';' }
        }
    }
    foreach ($key in @($updates.Keys)) {
        $found = $false
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($lines[$i] -match ('^\s*' + [regex]::Escape($key) + '\s*=')) {
                $lines[$i] = "$key=$($updates[$key])"
                $found = $true
                break
            }
        }
        if (!$found) { $lines.Insert($end, "$key=$($updates[$key])"); $end++ }
    }
    [System.IO.File]::WriteAllLines($configPath, $lines, $encoding)
}

Write-Output "Configured variant: $Variant"
if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath }
if ($RestartUbuntu) {
    Write-Output 'Restarting only Ubuntu to reload its WSLg instance.'
    & wsl.exe --terminate Ubuntu
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu termination failed.' }
    & wsl.exe -d Ubuntu --exec true
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu startup failed; restore with -Variant stock -RestartUbuntu.' }
}
