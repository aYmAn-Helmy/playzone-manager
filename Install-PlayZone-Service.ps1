#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$SourceRoot = $PSScriptRoot
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$ServiceName = 'PlayZoneManager'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { throw $Text }

Write-Host 'PlayZone Manager v0.31 - Remote Support Edition' -ForegroundColor Green
Write-Host 'Local backend + private Tailscale Serve support. Cloud Sync is disabled.'
Write-Host 'Installer is fully offline: Python and all dependencies are bundled.'

Step 'Stopping previous PlayZone service'
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
    }
}

Step 'Validating bundled offline runtime'
$PayloadRoot = Join-Path $SourceRoot 'offline-runtime'
foreach ($required in @((Join-Path $PayloadRoot 'python-3.12.6-embed-amd64.zip'),(Join-Path $PayloadRoot 'get-pip.py'),(Join-Path $PayloadRoot 'requirements-offline.txt'),(Join-Path $PayloadRoot 'wheels'))) {
    if (-not (Test-Path -LiteralPath $required)) { Fail "Offline installer payload missing: $required" }
}

Step 'Preparing installation folders'
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataRoot,(Join-Path $DataRoot 'logs') | Out-Null

# Preserve ProgramData across upgrades. Replace only application binaries.
Get-ChildItem -LiteralPath $InstallRoot -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'backend') -Destination (Join-Path $InstallRoot 'backend') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'frontend') -Destination (Join-Path $InstallRoot 'frontend') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'Bootstrap-Portable.ps1') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'Launch-PlayZone.ps1') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'VERSION.txt') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'PlayStation.ico') -Destination $InstallRoot -Force
foreach ($optionalFile in @('Setup-Tailscale-Support.ps1','Setup-Tailscale-Support.bat','Setup-Root-Password.ps1','Setup-Root-Password.bat','REMOTE-SUPPORT-SETUP-AR.txt','TAILSCALE-GRANTS-EXAMPLE.json')) {
    $src = Join-Path $SourceRoot $optionalFile
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $InstallRoot -Force }
}

Step 'Preparing self-contained local Python runtime'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'Bootstrap-Portable.ps1') -PayloadRoot $PayloadRoot
if ($LASTEXITCODE -ne 0) { Fail "Python runtime setup failed with exit code $LASTEXITCODE" }

$Python = Join-Path $InstallRoot '.runtime\python\python.exe'
$Pth = Join-Path $InstallRoot '.runtime\python\python312._pth'
$env:PLAYZONE_DB_PATH = Join-Path $DataRoot 'playzone.db'
if (-not (Test-Path $Python)) { Fail "Python runtime missing: $Python" }
if (-not (Test-Path $Pth)) { Fail "Python path file missing: $Pth" }

Step 'Configuring Python application path'
$lines = @(Get-Content -LiteralPath $Pth)
if ($lines -notcontains '..\..\backend') {
    $siteIndex = [Array]::IndexOf($lines, 'import site')
    if ($siteIndex -ge 0) {
        $before = @(); $after = @()
        if ($siteIndex -gt 0) { $before = $lines[0..($siteIndex-1)] }
        $after = $lines[$siteIndex..($lines.Length-1)]
        $lines = @($before + '..\..\backend' + $after)
    } else {
        $lines += '..\..\backend'
    }
    Set-Content -LiteralPath $Pth -Value $lines -Encoding ASCII
}

& $Python -c "import app.main, win32serviceutil, uvicorn; print('PlayZone service runtime OK')"
if ($LASTEXITCODE -ne 0) { Fail 'PlayZone service runtime import check failed.' }

Step 'Finalizing pywin32 for Windows Service support'
$PostInstall = Get-ChildItem -LiteralPath (Join-Path $InstallRoot '.runtime\python') -Filter 'pywin32_postinstall.py' -File -Recurse | Select-Object -First 1 -ExpandProperty FullName
if (-not $PostInstall -or -not (Test-Path -LiteralPath $PostInstall)) { Fail 'pywin32_postinstall.py was not found.' }
& $Python $PostInstall -install -quiet
if ($LASTEXITCODE -ne 0) { Fail "pywin32 service setup failed with exit code $LASTEXITCODE" }

$PyWin32ServiceExe = Join-Path $InstallRoot '.runtime\python\Lib\site-packages\win32\pythonservice.exe'
if (-not (Test-Path -LiteralPath $PyWin32ServiceExe)) {
    $PyWin32ServiceExe = Get-ChildItem -LiteralPath (Join-Path $InstallRoot '.runtime\python') -Filter 'pythonservice.exe' -File -Recurse | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $PyWin32ServiceExe -or -not (Test-Path -LiteralPath $PyWin32ServiceExe)) { Fail 'pythonservice.exe was not installed by pywin32.' }

Step 'Securing ROOT account'
& $Python -m app.root_setup status | Out-Host
$rootStatus = $LASTEXITCODE
if ($rootStatus -eq 3) {
    Write-Host 'ROOT password setup is required for v0.31 Remote Support.' -ForegroundColor Yellow
    while ($true) {
        $secure1 = Read-Host 'Enter a new ROOT password (minimum 12 characters)' -AsSecureString
        $secure2 = Read-Host 'Confirm ROOT password' -AsSecureString
        $bstr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
        $bstr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
        try {
            $plain1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr1)
            $plain2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr2)
            if ($plain1.Length -lt 12) {
                Write-Host 'Password must be at least 12 characters.' -ForegroundColor Red
                continue
            }
            if ($plain1 -cne $plain2) {
                Write-Host 'Passwords do not match.' -ForegroundColor Red
                continue
            }
            $plain1 | & $Python -m app.root_setup set
            if ($LASTEXITCODE -ne 0) { Fail 'ROOT password setup failed.' }
            Write-Host 'ROOT password configured. Passwordless privileged mode is disabled.' -ForegroundColor Green
            break
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
            $plain1 = $null
            $plain2 = $null
        }
    }
} elseif ($rootStatus -eq 0) {
    Write-Host 'Existing ROOT password retained.' -ForegroundColor Green
} else {
    Fail "Could not determine ROOT password setup state. Exit code: $rootStatus"
}

Step 'Installing Windows Service' 
$ServiceScript = Join-Path $InstallRoot 'backend\app\windows_service.py'
if ($existing) {
    & cmd.exe /d /c 'sc.exe delete PlayZoneManager >nul 2>&1' | Out-Null
    $global:LASTEXITCODE = 0
    Start-Sleep -Milliseconds 1200
}
& $Python $ServiceScript --startup auto install
if ($LASTEXITCODE -ne 0) { Fail "Windows Service install failed with exit code $LASTEXITCODE" }

# Make the service resilient to transient crashes.
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null
& sc.exe failureflag $ServiceName 1 | Out-Null

Step 'Configuring Tailscale always-on recovery'
$TailscaleService = Get-Service -Name 'Tailscale' -ErrorAction SilentlyContinue
if ($TailscaleService) {
    & sc.exe config Tailscale start= auto | Out-Null
    & sc.exe failure Tailscale reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null
    & sc.exe failureflag Tailscale 1 | Out-Null
    Start-Service -Name 'Tailscale' -ErrorAction SilentlyContinue
}

Step 'Configuring Voltra firewall'
& netsh.exe advfirewall firewall delete rule name='PlayZone Manager Voltra TCP' | Out-Null
& netsh.exe advfirewall firewall add rule name='PlayZone Manager Voltra TCP' dir=in action=allow protocol=TCP localport=10086 profile=private | Out-Null

Step 'Creating shortcuts and login launcher'
$Launcher = Join-Path $InstallRoot 'Launch-PlayZone.ps1'
$Shell = New-Object -ComObject WScript.Shell
$shortcutTargets = @(
    (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'PlayZone Manager.lnk'),
    (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'PlayZone Manager.lnk'),
    (Join-Path ([Environment]::GetFolderPath('CommonStartup')) 'PlayZone Manager.lnk')
)
foreach ($path in $shortcutTargets) {
    $s = $Shell.CreateShortcut($path)
    $s.TargetPath = 'powershell.exe'
    $s.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Launcher + '"'
    $s.WorkingDirectory = $InstallRoot
    $s.Description = 'PlayZone Manager'
    $s.IconLocation = (Join-Path $InstallRoot 'PlayStation.ico') + ',0'
    $s.Save()
}

Step 'Starting PlayZone Manager Service'
Start-Service -Name $ServiceName
$svc = Get-Service -Name $ServiceName
$svc.WaitForStatus('Running', [TimeSpan]::FromSeconds(20))

$healthy = $false
for ($i=0; $i -lt 120; $i++) {
    try {
        $h = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 'http://127.0.0.1:8000/api/health'
        if ($h.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $healthy) {
    Fail "Service started but Local Web did not become healthy. Check $DataRoot\logs\service.log"
}

try {
    $ui = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:8000/'
    if ($ui.StatusCode -ne 200 -or $ui.Content.Length -lt 100) { Fail 'Local Web UI did not load correctly.' }
} catch {
    Fail "Local Web API is healthy but the cashier UI failed to load: $($_.Exception.Message)"
}

Step 'Verifying Voltra TCP listener'
$tcpOk = $false
try {
    $c = New-Object Net.Sockets.TcpClient
    $iar = $c.BeginConnect('127.0.0.1',10086,$null,$null)
    $tcpOk = $iar.AsyncWaitHandle.WaitOne(3000) -and $c.Connected
    $c.Close()
} catch { }
if (-not $tcpOk) { Fail 'Voltra TCP 10086 is not listening. Check service.log before using the system.' }

Step 'Opening PlayZone Manager'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $Launcher

Write-Host ''
Write-Host '===================================================' -ForegroundColor Green
Write-Host ' PlayZone Manager Service installation completed' -ForegroundColor Green
Write-Host '===================================================' -ForegroundColor Green
Write-Host 'Local Web   : http://127.0.0.1:8000'
Write-Host 'Voltra TCP  : 10086'
Write-Host "Data        : $DataRoot"
Write-Host "Service log : $DataRoot\logs\service.log"
Write-Host 'Cloud Sync  : DISABLED'
Write-Host 'Internet    : Only required for Tailscale remote support'
Write-Host 'Remote setup: Run Setup-Tailscale-Support.bat as Administrator after Tailscale is installed'
Write-Host ''
Read-Host 'Press Enter to close'
