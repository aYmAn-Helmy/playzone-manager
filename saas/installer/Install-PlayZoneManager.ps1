#Requires -RunAsAdministrator
param(
    [string]$BundleRoot = $PSScriptRoot,
    [string]$CloudUrl = 'https://playzone-cloud-production.up.railway.app',
    [string]$InstallationCode = '',
    [switch]$SkipCloudActivation
)

$ErrorActionPreference = 'Stop'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$RuntimeDest = Join-Path $InstallRoot 'runtime'
$DesktopDest = Join-Path $InstallRoot 'desktop'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$RuntimeSource = Join-Path $BundleRoot 'runtime'
$DesktopSource = Join-Path $BundleRoot 'desktop'
$TaskName = 'PlayZone Manager Edge'

function Step([string]$Text) {
    Write-Host "`n==> $Text" -ForegroundColor Cyan
}

function Wait-Edge([int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 'http://127.0.0.1:8000/api/health'
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (-not (Test-Path $RuntimeSource)) { throw "Missing runtime folder: $RuntimeSource" }
if (-not (Test-Path $DesktopSource)) { throw "Missing desktop folder: $DesktopSource" }
if (-not (Test-Path (Join-Path $DesktopSource 'PlayZoneManager.exe'))) { throw 'PlayZoneManager.exe is missing from desktop folder.' }

Write-Host 'PlayZone Manager v0.28 SaaS Prototype' -ForegroundColor Green
Write-Host 'This installer requires Internet only during first-time local Python setup and Cloud activation.'

Step 'Stopping previous Edge instance'
# First-time installs do not have the task yet. Ignore that expected condition.
& cmd.exe /d /c ('schtasks.exe /End /TN "{0}" >nul 2>&1' -f $TaskName) | Out-Null
$global:LASTEXITCODE = 0
Start-Sleep -Milliseconds 500

Step 'Copying PlayZone Manager files'
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataRoot,(Join-Path $DataRoot 'logs') | Out-Null
if (Test-Path $RuntimeDest) { Remove-Item -Recurse -Force $RuntimeDest }
if (Test-Path $DesktopDest) { Remove-Item -Recurse -Force $DesktopDest }
Copy-Item -Recurse -Force $RuntimeSource $RuntimeDest
Copy-Item -Recurse -Force $DesktopSource $DesktopDest
Copy-Item -Force (Join-Path $BundleRoot 'Start-PlayZoneEdge.ps1') (Join-Path $RuntimeDest 'Start-PlayZoneEdge.ps1')

Step 'Preparing local Python runtime'
$Bootstrap = Join-Path $RuntimeDest 'Bootstrap-Portable.ps1'
if (-not (Test-Path $Bootstrap)) { throw "Missing bootstrap: $Bootstrap" }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Bootstrap
if ($LASTEXITCODE -ne 0) { throw "Portable runtime setup failed with exit code $LASTEXITCODE" }

$Python = Join-Path $RuntimeDest '.runtime\python\python.exe'
if (-not (Test-Path $Python)) { throw "Portable Python was not created: $Python" }

Step 'Configuring portable Python application path'
$Pth = Join-Path $RuntimeDest '.runtime\python\python312._pth'
if (-not (Test-Path $Pth)) { throw "Portable Python path file is missing: $Pth" }
$PthLines = @(Get-Content -LiteralPath $Pth)
if ($PthLines -notcontains '..\..\backend') {
    $SiteIndex = [Array]::IndexOf($PthLines, 'import site')
    if ($SiteIndex -ge 0) {
        $Before = @()
        $After = @()
        if ($SiteIndex -gt 0) { $Before = $PthLines[0..($SiteIndex-1)] }
        $After = $PthLines[$SiteIndex..($PthLines.Length-1)]
        $PthLines = @($Before + '..\..\backend' + $After)
    } else {
        $PthLines += '..\..\backend'
    }
    Set-Content -LiteralPath $Pth -Value $PthLines -Encoding ASCII
}

& $Python -c "import app, app.edge_runtime; print('PlayZone Edge import OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python cannot import PlayZone backend from $RuntimeDest\backend"
}

$env:PLAYZONE_DB_PATH = Join-Path $DataRoot 'playzone.db'
$env:PLAYZONE_EDGE_DB_PATH = Join-Path $DataRoot 'edge.db'
$env:VOLTRA_DATA_PATH = Join-Path $DataRoot 'voltra.json'
$env:PLAYZONE_EDGE_APP_VERSION = '0.28-saas-prototype'

if (-not $SkipCloudActivation) {
    Step 'Linking this PC to PlayZone Cloud'
    if ([string]::IsNullOrWhiteSpace($CloudUrl)) {
        $CloudUrl = Read-Host 'Cloud URL'
    } else {
        Write-Host "Cloud: $CloudUrl"
    }
    if ([string]::IsNullOrWhiteSpace($InstallationCode)) {
        $InstallationCode = Read-Host 'Installation Code from Platform Admin'
    }
    if ([string]::IsNullOrWhiteSpace($InstallationCode)) {
        throw 'Installation Code is required.'
    }

    Push-Location (Join-Path $RuntimeDest 'backend')
    try {
        $NormalizedCloudUrl = $CloudUrl.TrimEnd('/')
        $StatusJson = & $Python -m app.edge_runtime status
        $StatusExitCode = $LASTEXITCODE
        $ExistingActivation = $null
        if ($StatusExitCode -eq 0) {
            try { $ExistingActivation = $StatusJson | ConvertFrom-Json } catch { }
        }

        if ($ExistingActivation.activated -and $ExistingActivation.cloud_url.TrimEnd('/') -eq $NormalizedCloudUrl) {
            Write-Host "This PC is already linked to device $($ExistingActivation.device_id); keeping the existing activation."
        } else {
            & $Python -m app.edge_runtime activate --cloud-url $NormalizedCloudUrl --installation-code $InstallationCode.Trim()
            if ($LASTEXITCODE -ne 0) { throw "Cloud activation failed with exit code $LASTEXITCODE" }
        }
    } finally {
        Pop-Location
    }
}

Step 'Configuring Voltra firewall rule'
netsh advfirewall firewall delete rule name='PlayZone Manager Voltra TCP' | Out-Null
netsh advfirewall firewall add rule name='PlayZone Manager Voltra TCP' dir=in action=allow protocol=TCP localport=10086 profile=private | Out-Null

Step 'Installing Edge auto-start task'
$EdgeScript = Join-Path $RuntimeDest 'Start-PlayZoneEdge.ps1'

# Use the ScheduledTasks PowerShell API instead of schtasks.exe /TR.
# This avoids quoting failures when Program Files paths contain spaces.
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

$TaskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $EdgeScript)
$TaskTrigger = New-ScheduledTaskTrigger -AtStartup
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $TaskTrigger -Principal $TaskPrincipal -Description 'PlayZone Manager Local Edge runtime' -Force | Out-Null

Step 'Creating shortcuts'
$DesktopExe = Join-Path $DesktopDest 'PlayZoneManager.exe'
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

Step 'Starting Local Edge'
Start-ScheduledTask -TaskName $TaskName
if (Wait-Edge 75) {
    Write-Host '[OK] Local Edge is online: http://127.0.0.1:8000' -ForegroundColor Green
} else {
    Write-Warning "Local Edge did not answer within 75 seconds. Check: $DataRoot\logs\edge.log"
}

Step 'Starting PlayZone Manager Desktop'
Start-Process -FilePath $DesktopExe -WorkingDirectory $DesktopDest

Write-Host ''
Write-Host '=============================================' -ForegroundColor Green
Write-Host ' PlayZone Manager installation completed' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Green
Write-Host "Application : $DesktopExe"
Write-Host 'Local Edge  : http://127.0.0.1:8000'
Write-Host 'Voltra TCP  : 10086 (Private network only)'
Write-Host "Data        : $DataRoot"
Write-Host "Edge log    : $DataRoot\logs\edge.log"
Write-Host ''
Write-Host 'After the first successful setup, cashier/session/Voltra runtime can continue locally if Internet is disconnected.'
Read-Host 'Press Enter to close installer'
