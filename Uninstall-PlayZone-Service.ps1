#Requires -RunAsAdministrator
param([switch]$RemoveData)
$ErrorActionPreference='Continue'
$InstallRoot=Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot=Join-Path $env:ProgramData 'PlayZone Manager'
$Python=Join-Path $InstallRoot '.runtime\python\python.exe'
$ServiceScript=Join-Path $InstallRoot 'backend\app\windows_service.py'
$Cloudflared=Join-Path $InstallRoot 'cloudflared.exe'
$CloudflareState=Join-Path $DataRoot 'cloudflare-quick\state.json'
if(Test-Path -LiteralPath $CloudflareState){
  try {
    $state=Get-Content -LiteralPath $CloudflareState -Raw | ConvertFrom-Json
    if($state.pid){ Stop-Process -Id ([int]$state.pid) -Force -ErrorAction SilentlyContinue }
  } catch { }
}
try {
  Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $Cloudflared } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch { }
if(Get-Service -Name 'PlayZoneManager' -ErrorAction SilentlyContinue){
  Stop-Service -Name 'PlayZoneManager' -Force -ErrorAction SilentlyContinue
  if((Test-Path $Python) -and (Test-Path $ServiceScript)){ & $Python $ServiceScript remove 2>$null | Out-Null }
  sc.exe delete PlayZoneManager 2>$null | Out-Null
}
netsh.exe advfirewall firewall delete rule name='PlayZone Manager Voltra TCP' | Out-Null
foreach($p in @(
  (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'PlayZone Manager.lnk'),
  (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'PlayZone Manager.lnk'),
  (Join-Path ([Environment]::GetFolderPath('CommonStartup')) 'PlayZone Manager.lnk')
)){ Remove-Item -Force $p -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force $InstallRoot -ErrorAction SilentlyContinue
if($RemoveData){ Remove-Item -Recurse -Force $DataRoot -ErrorAction SilentlyContinue }
Write-Host 'PlayZone Manager Service removed.'
if(-not $RemoveData){ Write-Host "Data kept at: $DataRoot" }
