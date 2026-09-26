#Requires -RunAsAdministrator
param([switch]$RemoveData)

$ErrorActionPreference = 'Continue'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'

schtasks.exe /End /TN 'PlayZone Manager Edge' 2>$null | Out-Null
schtasks.exe /Delete /F /TN 'PlayZone Manager Edge' 2>$null | Out-Null
netsh advfirewall firewall delete rule name='PlayZone Manager Voltra TCP' | Out-Null

Remove-Item -Force (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'PlayZone Manager.lnk') -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'PlayZone Manager.lnk') -ErrorAction SilentlyContinue

if (Test-Path $InstallRoot) { Remove-Item -Recurse -Force $InstallRoot }
if ($RemoveData -and (Test-Path $DataRoot)) { Remove-Item -Recurse -Force $DataRoot }

Write-Host 'PlayZone Manager removed.'
if (-not $RemoveData) {
    Write-Host "Customer data was kept at: $DataRoot"
}
