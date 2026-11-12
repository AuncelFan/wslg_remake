param(
    [Parameter(Mandatory=$true)][ValidateSet('baseline','acked','original')][string]$Variant,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9-]+$')][string]$SessionName,
    [switch]$RestartUbuntu
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$config=Join-Path $env:USERPROFILE '.wslgconfig'
$evidence=Join-Path $root 'evidence\desktop-state-20261112'
$session=Join-Path $evidence $SessionName
if (Test-Path -LiteralPath $session) { throw 'Choose a new session name; preserving prior evidence.' }
New-Item -ItemType Directory -Path $session | Out-Null
Copy-Item -LiteralPath $config -Destination (Join-Path $session 'wslgconfig.before')
$lines=[System.Collections.Generic.List[string]]::new()
foreach($line in [IO.File]::ReadAllLines($config)) { $lines.Add($line) }
$start=$lines.IndexOf('[system-distro-env]')
if($start -lt 0) { throw 'Inspect the existing WSLg configuration before proceeding.' }
$end=$lines.Count
for($i=$start+1;$i -lt $lines.Count;$i++) { if($lines[$i] -match '^\s*\[') { $end=$i; break } }
$mapIndex=-1; $logIndex=-1
for($i=$start+1;$i -lt $end;$i++) {
    if($lines[$i] -match '^WESTON_MODULE_MAP=') { $mapIndex=$i }
    if($lines[$i] -match '^WSLG_WESTON_LOG_PATH=') { $logIndex=$i }
}
if($mapIndex -lt 0 -or $logIndex -lt 0) { throw 'Expected existing RDP experiment configuration.' }
$maps=@(($lines[$mapIndex] -replace '^WESTON_MODULE_MAP=','').Split(';') | Where-Object { $_ -and $_ -notmatch '^rdprail-shell\.so=' })
if($Variant -ne 'original') {
    $module=Join-Path $root ('.work\native-desktop-20261112\'+$Variant+'\rdprail-shell.so')
    if(!(Test-Path -LiteralPath $module)) { throw 'Build and preflight the library first.' }
    $linux='/mnt/'+$module.Substring(0,1).ToLower()+$module.Substring(2).Replace('\','/')
    $maps+=('rdprail-shell.so='+$linux)
}
$lines[$mapIndex]='WESTON_MODULE_MAP='+($maps -join ';')
$logPath=Join-Path $session 'weston.log'
$lines[$logIndex]='WSLG_WESTON_LOG_PATH=/mnt/'+$logPath.Substring(0,1).ToLower()+$logPath.Substring(2).Replace('\','/')
[IO.File]::WriteAllLines($config,$lines,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath $config -Destination (Join-Path $session 'wslgconfig.active')
@{at=(Get-Date -Format o);variant=$Variant;session=$SessionName;restart_ubuntu=[bool]$RestartUbuntu;preserved_other_module_maps=$true} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $session 'deployment.json')
Get-Content -LiteralPath $config
if($RestartUbuntu) {
    & wsl.exe --terminate Ubuntu
    if($LASTEXITCODE -ne 0) { throw 'Ubuntu termination failed.' }
    & wsl.exe -d Ubuntu --exec true
    if($LASTEXITCODE -ne 0) { throw 'Ubuntu startup failed; restore the saved configuration.' }
}
