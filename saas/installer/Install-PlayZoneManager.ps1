#Requires -RunAsAdministrator
param(
    [string]$BundleRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = 'Stop'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$RuntimeDest = Join-Path $InstallRoot 'runtime'
$DesktopDest = Join-Path $InstallRoot 'desktop'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$RuntimeSource = Join-Path $BundleRoot 'runtime'
$DesktopSource = Join-Path $BundleRoot 'desktop'

if (-not (Test-Path $RuntimeSource)) { throw "Missing bundle runtime directory: $RuntimeSource" }
if (-not (Test-Path $DesktopSource)) { throw "Missing bundle desktop directory: $DesktopSource" }

Write-Host 'Installing PlayZone Manager...' -ForegroundColor Cyan

schtasks.exe /End /TN 'PlayZone Manager Edge' 2>$null | Out-Null

New-Item -ItemType Directory -Force -Path $InstallRoot,$DataRoot | Out-Null
if (Test-Path $RuntimeDest) { Remove-Item -Recurse -Force $RuntimeDest }
if (Test-Path $DesktopDest) { Remove-Item -Recurse -Force $DesktopDest }
Copy-Item -Recurse -Force $RuntimeSource $RuntimeDest
Copy-Item -Recurse -Force $DesktopSource $DesktopDest
Copy-Item -Force (Join-Path $BundleRoot 'Start-PlayZoneEdge.ps1') (Join-Path $RuntimeDest 'Start-PlayZoneEdge.ps1')

$Setup = Join-Path $RuntimeDest 'Setup-Portable.bat'
if (Test-Path $Setup) {
    Push-Location $RuntimeDest
    try {
        & cmd.exe /c '"Setup-Portable.bat"'
        if ($LASTEXITCODE -ne 0) { throw "Portable runtime setup failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

netsh advfirewall firewall delete rule name='PlayZone Manager Voltra TCP' | Out-Null
netsh advfirewall firewall add rule name='PlayZone Manager Voltra TCP' dir=in action=allow protocol=TCP localport=10086 profile=private | Out-Null

$EdgeScript = Join-Path $RuntimeDest 'Start-PlayZoneEdge.ps1'
$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$EdgeScript`""
schtasks.exe /Create /F /SC ONSTART /RU SYSTEM /RL HIGHEST /TN 'PlayZone Manager Edge' /TR $TaskCommand | Out-Null
schtasks.exe /Run /TN 'PlayZone Manager Edge' | Out-Null

$DesktopExe = Join-Path $DesktopDest 'PlayZoneManager.exe'
if (-not (Test-Path $DesktopExe)) { throw "Desktop executable missing: $DesktopExe" }
$Shell = New-Object -ComObject WScript.Shell
foreach ($ShortcutPath in @(
    (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'PlayZone Manager.lnk'),
    (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'PlayZone Manager.lnk')
)) {
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $DesktopExe
    $Shortcut.WorkingDirectory = $DesktopDest
    $Shortcut.Description = 'PlayZone Manager'
    $Shortcut.Save()
}

Write-Host ''
Write-Host 'PlayZone Manager installed successfully.' -ForegroundColor Green
Write-Host "Application : $DesktopExe"
Write-Host "Local Edge  : http://127.0.0.1:8000"
Write-Host "Voltra TCP  : 10086 (Private network only)"
Write-Host "Data        : $DataRoot"
