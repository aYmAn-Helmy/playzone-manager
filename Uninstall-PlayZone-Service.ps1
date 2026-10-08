#Requires -RunAsAdministrator
param(
    [switch]$RemoveData,
    [switch]$RemoveTailscale
)

$ErrorActionPreference = 'Continue'
$ServiceName = 'PlayZoneManager'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

Write-Host 'ZoneXplay - Complete Uninstaller' -ForegroundColor Yellow
Write-Host 'Removes ZoneXplay service components, shortcuts, firewall rules and application files.'
Write-Host 'Tailscale itself is NOT removed unless -RemoveTailscale is explicitly supplied.'

Step 'Stopping and removing Windows service'
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}
# Delete directly even if the bundled Python runtime is damaged/missing.
& sc.exe stop $ServiceName 2>$null | Out-Null
& sc.exe delete $ServiceName 2>$null | Out-Null

Step 'Removing ZoneXplay Tailscale Serve configuration'
$tailscaleCandidates = @(
    (Get-Command tailscale.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
$tailscaleExe = $tailscaleCandidates | Select-Object -First 1
if ($tailscaleExe) {
    & $tailscaleExe serve --https=443 off 2>$null | Out-Null
    if ($RemoveTailscale) {
        & $tailscaleExe down 2>$null | Out-Null
        Stop-Service -Name 'Tailscale' -Force -ErrorAction SilentlyContinue
        & sc.exe delete Tailscale 2>$null | Out-Null
        foreach ($dir in @(
            (Join-Path $env:ProgramFiles 'Tailscale'),
            (Join-Path ${env:ProgramFiles(x86)} 'Tailscale')
        )) { if ($dir) { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue } }
    }
}

Step 'Removing firewall rules'
foreach ($rule in @(
    'ZoneXplay Voltra TCP',
    'nourxplay Voltra TCP',
    'PlayZone Manager Voltra TCP'
)) {
    & netsh.exe advfirewall firewall delete rule name=$rule 2>$null | Out-Null
}

Step 'Removing shortcuts and startup launchers'
$shortcutNames = @('ZoneXplay.lnk','nourxplay.lnk','PlayZone Manager.lnk')
$shortcutFolders = @(
    [Environment]::GetFolderPath('CommonDesktopDirectory'),
    [Environment]::GetFolderPath('CommonPrograms'),
    [Environment]::GetFolderPath('CommonStartup'),
    [Environment]::GetFolderPath('DesktopDirectory'),
    [Environment]::GetFolderPath('Programs'),
    [Environment]::GetFolderPath('Startup')
) | Where-Object { $_ }
foreach ($folder in $shortcutFolders) {
    foreach ($name in $shortcutNames) {
        Remove-Item -LiteralPath (Join-Path $folder $name) -Force -ErrorAction SilentlyContinue
    }
}

Step 'Stopping ZoneXplay Desktop/Chromium processes'
Get-Process -Name 'ZoneXplay' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name 'nourxplay' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name 'PlayZone Manager' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Step 'Stopping leftover application processes'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallRoot,[StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine -like '*127.0.0.1:8000*')
    } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Step 'Removing application files'
Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue

if ($RemoveData) {
    Step 'Removing database, logs and saved configuration'
    Remove-Item -LiteralPath $DataRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Application data removed.' -ForegroundColor Yellow
} else {
    Write-Host "Data/database kept at: $DataRoot" -ForegroundColor Green
    Write-Host 'To delete it too, run the uninstaller with -RemoveData.'
}

Step 'Final service check'
$left = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($left) {
    Write-Host "WARNING: $ServiceName still exists. Restart Windows, then run this uninstaller again." -ForegroundColor Red
    exit 2
}

Write-Host ''
Write-Host 'ZoneXplay / ZoneXplay service components were removed successfully.' -ForegroundColor Green
if (-not $RemoveTailscale) {
    Write-Host 'Tailscale application/service was left installed because it is an external dependency.' -ForegroundColor DarkGray
}
