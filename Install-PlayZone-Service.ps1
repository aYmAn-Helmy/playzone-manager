#Requires -RunAsAdministrator
param([switch]$NonInteractive)

$ErrorActionPreference = 'Stop'
$SourceRoot = $PSScriptRoot
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$SecureDataRoot = Join-Path $DataRoot 'secure-data'
$ServiceName = 'PlayZoneManager'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { throw $Text }
function Get-Sha256Hex([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $bytes = $sha.ComputeHash($stream)
        return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

Write-Host 'PlayZone Manager v0.34.6 - Secure Cash Drawer Edition' -ForegroundColor Green
Write-Host 'Local backend + private Tailscale Serve support. Cloud Sync is disabled.'
Write-Host 'Python is bundled offline. The installer downloads and verifies the official Electron/Chromium desktop runtime once if it is not bundled beside the installer.'

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
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataRoot,(Join-Path $DataRoot 'logs'),$SecureDataRoot | Out-Null

Step 'Migrating financial data to protected storage'
$SecureDb = Join-Path $SecureDataRoot 'playzone.db'
$LegacyDb = Join-Path $DataRoot 'playzone.db'
if ((Test-Path -LiteralPath $SecureDb) -and (Test-Path -LiteralPath $LegacyDb)) {
    Fail "Both legacy and secure PlayZone databases exist. Installation stopped to avoid choosing the wrong financial database. Keep the correct database and move the other one aside, then run the installer again."
}
if (-not (Test-Path -LiteralPath $SecureDb) -and (Test-Path -LiteralPath $LegacyDb)) {
    foreach ($name in @('playzone.db','playzone.db-wal','playzone.db-shm')) {
        $legacy = Join-Path $DataRoot $name
        if (Test-Path -LiteralPath $legacy) {
            Move-Item -LiteralPath $legacy -Destination (Join-Path $SecureDataRoot $name) -Force
        }
    }
    Write-Host 'Existing PlayZone database moved into secure-data.' -ForegroundColor Green
}

$LegacyVoltra = Join-Path $DataRoot 'voltra.json'
$SecureVoltra = Join-Path $SecureDataRoot 'voltra.json'
if (Test-Path -LiteralPath $LegacyVoltra) {
    if (-not (Test-Path -LiteralPath $SecureVoltra)) {
        Move-Item -LiteralPath $LegacyVoltra -Destination $SecureVoltra -Force
    } else {
        $archiveName = 'voltra-legacy-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
        Move-Item -LiteralPath $LegacyVoltra -Destination (Join-Path $SecureDataRoot $archiveName) -Force
    }
}

$LegacyBackups = Join-Path $DataRoot 'backups'
$SecureBackups = Join-Path $SecureDataRoot 'backups'
if (Test-Path -LiteralPath $LegacyBackups) {
    New-Item -ItemType Directory -Force -Path $SecureBackups | Out-Null
    foreach ($legacyBackup in Get-ChildItem -LiteralPath $LegacyBackups -File -Force -ErrorAction SilentlyContinue) {
        $destination = Join-Path $SecureBackups $legacyBackup.Name
        if (Test-Path -LiteralPath $destination) {
            $destination = Join-Path $SecureBackups ('legacy-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $legacyBackup.Name)
        }
        Move-Item -LiteralPath $legacyBackup.FullName -Destination $destination -Force
    }
    Remove-Item -LiteralPath $LegacyBackups -Recurse -Force -ErrorAction SilentlyContinue
}


Step 'Protecting database and backups from standard Windows users'
# Keep desktop-profile/cache outside this directory. Only LocalSystem (the
# Windows service) and elevated Administrators can read or modify secure-data.
& icacls.exe $SecureDataRoot /inheritance:r /Q | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'Could not disable inherited permissions on secure-data.' }
& icacls.exe $SecureDataRoot /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'Could not grant SYSTEM/Administrators access to secure-data.' }
Get-ChildItem -LiteralPath $SecureDataRoot -Force -ErrorAction SilentlyContinue | ForEach-Object {
    & icacls.exe $_.FullName /reset /T /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "Could not reset protected ACLs below secure-data: $($_.FullName)" }
}

# Preserve ProgramData across upgrades. Replace only application binaries.
Get-ChildItem -LiteralPath $InstallRoot -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'backend') -Destination (Join-Path $InstallRoot 'backend') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'frontend') -Destination (Join-Path $InstallRoot 'frontend') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'desktop-shell') -Destination (Join-Path $InstallRoot 'desktop-shell') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'Bootstrap-Portable.ps1') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'Launch-PlayZone.ps1') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'VERSION.txt') -Destination $InstallRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'PlayStation.ico') -Destination $InstallRoot -Force
foreach ($optionalFile in @('Uninstall-PlayZone-Service.ps1','Uninstall-PlayZone-Service.bat','Setup-Tailscale-Support.ps1','Setup-Tailscale-Support.bat','Setup-Root-Password.ps1','Setup-Root-Password.bat','REMOTE-SUPPORT-SETUP-AR.txt','TAILSCALE-GRANTS-EXAMPLE.json')) {
    $src = Join-Path $SourceRoot $optionalFile
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $InstallRoot -Force }
}

Step 'Preparing self-contained local Python runtime'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'Bootstrap-Portable.ps1') -PayloadRoot $PayloadRoot
if ($LASTEXITCODE -ne 0) { Fail "Python runtime setup failed with exit code $LASTEXITCODE" }

$Python = Join-Path $InstallRoot '.runtime\python\python.exe'
$Pth = Join-Path $InstallRoot '.runtime\python\python312._pth'
$env:PLAYZONE_DB_PATH = Join-Path $SecureDataRoot 'playzone.db'
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
    if ($NonInteractive) {
        Fail 'ROOT password setup is required before a non-interactive installation can continue.'
    }
    Write-Host 'ROOT password setup is required for v0.34.6 Secure Cash Drawer Edition.' -ForegroundColor Yellow
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
& netsh.exe advfirewall firewall add rule name='PlayZone Manager Voltra TCP' dir=in action=allow protocol=TCP localport=10086 profile=any remoteip=localsubnet | Out-Null

Step 'Preparing self-contained Chromium desktop runtime'
$ElectronVersion = '44.4.5'
$ElectronArchive = "electron-v$ElectronVersion-win32-x64.zip"
$ElectronUrl = "https://github.com/electron/electron/releases/download/v$ElectronVersion/$ElectronArchive"
$ElectronSha256 = '11c395820a5aaa8ebcc0686b476d0ac98a730274ebfbdc8cf5538a7c2815cb5d'
$DesktopRuntime = Join-Path $InstallRoot 'desktop-runtime'
$DesktopExe = Join-Path $DesktopRuntime 'PlayZone Manager.exe'
$BundledElectron = Join-Path (Join-Path $SourceRoot 'desktop-runtime') $ElectronArchive
$ElectronCacheRoot = Join-Path $DataRoot 'cache'
$CachedElectron = Join-Path $ElectronCacheRoot $ElectronArchive
$TempElectron = Join-Path $env:TEMP $ElectronArchive
New-Item -ItemType Directory -Force -Path $ElectronCacheRoot | Out-Null

if (Test-Path -LiteralPath $DesktopRuntime) { Remove-Item -LiteralPath $DesktopRuntime -Recurse -Force }
New-Item -ItemType Directory -Force -Path $DesktopRuntime | Out-Null

$ElectronZip = $null
if (Test-Path -LiteralPath $BundledElectron) {
    $ElectronZip = $BundledElectron
    Write-Host 'Using bundled Electron/Chromium runtime.' -ForegroundColor Green
} elseif (Test-Path -LiteralPath $CachedElectron) {
    $ElectronZip = $CachedElectron
    Write-Host 'Using cached Electron/Chromium runtime from ProgramData.' -ForegroundColor Green
} else {
    Write-Host "Downloading official Electron $ElectronVersion desktop runtime (~151 MB)..." -ForegroundColor Yellow
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $ElectronUrl -OutFile $TempElectron
        $ElectronZip = $TempElectron
    } catch {
        Fail "Could not download the desktop browser runtime. Internet is required once during v0.34.5 installation unless $ElectronArchive is placed inside a desktop-runtime folder beside the installer. $($_.Exception.Message)"
    }
}

$actualElectronHash = Get-Sha256Hex $ElectronZip
if ($actualElectronHash -ne $ElectronSha256) {
    if ($ElectronZip -eq $CachedElectron) { Remove-Item -LiteralPath $CachedElectron -Force -ErrorAction SilentlyContinue }
    Fail "Electron runtime checksum mismatch. Expected $ElectronSha256 but received $actualElectronHash"
}
if ($ElectronZip -eq $TempElectron) { Copy-Item -LiteralPath $TempElectron -Destination $CachedElectron -Force }
Expand-Archive -LiteralPath $ElectronZip -DestinationPath $DesktopRuntime -Force
if (-not (Test-Path -LiteralPath (Join-Path $DesktopRuntime 'electron.exe'))) { Fail 'Electron runtime extraction did not produce electron.exe.' }
Move-Item -LiteralPath (Join-Path $DesktopRuntime 'electron.exe') -Destination $DesktopExe -Force
if ($ElectronZip -eq $TempElectron) { Remove-Item -LiteralPath $TempElectron -Force -ErrorAction SilentlyContinue }
if (-not (Test-Path -LiteralPath $DesktopExe)) { Fail 'PlayZone Manager desktop executable was not created.' }
Write-Host "Desktop browser ready: $DesktopExe" -ForegroundColor Green

Step 'Creating verified desktop/start shortcuts'
$Launcher = Join-Path $InstallRoot 'Launch-PlayZone.ps1'
$DesktopShell = Join-Path $InstallRoot 'desktop-shell'
$WshShell = New-Object -ComObject WScript.Shell

function New-PlayZoneShortcut([string]$Folder) {
    if ([string]::IsNullOrWhiteSpace($Folder)) { return $null }
    try {
        New-Item -ItemType Directory -Force -Path $Folder | Out-Null
        $path = Join-Path $Folder 'PlayZone Manager.lnk'
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        $s = $WshShell.CreateShortcut($path)
        $s.TargetPath = $DesktopExe
        $s.Arguments = '"' + $DesktopShell + '"'
        $s.WorkingDirectory = $DesktopRuntime
        $s.Description = 'PlayZone Manager Desktop Edition'
        $s.IconLocation = (Join-Path $InstallRoot 'PlayStation.ico') + ',0'
        $s.Save()
        if (-not (Test-Path -LiteralPath $path)) { throw "Shortcut was not created: $path" }

        # Re-open the shortcut and verify that it actually points to the installed desktop client.
        $check = $WshShell.CreateShortcut($path)
        if ($check.TargetPath -ne $DesktopExe) { throw "Shortcut target mismatch: $path" }
        return $path
    } catch {
        Write-Warning "Could not create shortcut in '$Folder': $($_.Exception.Message)"
        return $null
    }
}

# Resolve the actual interactive Windows user's profile even when the installer
# is elevated with a different Administrator account. This avoids creating the
# customer shortcut only on the administrator's Desktop.
$interactiveDesktopCandidates = @()
try {
    $explorer = Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" -ErrorAction Stop | Select-Object -First 1
    if ($explorer) {
        $owner = Invoke-CimMethod -InputObject $explorer -MethodName GetOwner -ErrorAction Stop
        if ($owner -and $owner.User) {
            $accountName = if ($owner.Domain) { "$($owner.Domain)\$($owner.User)" } else { $owner.User }
            try {
                $sid = (New-Object System.Security.Principal.NTAccount($accountName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
                $profile = Get-CimInstance Win32_UserProfile -Filter "SID='$sid'" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($profile -and $profile.LocalPath) {
                    $interactiveDesktopCandidates += (Join-Path $profile.LocalPath 'Desktop')
                    $interactiveDesktopCandidates += (Join-Path $profile.LocalPath 'OneDrive\Desktop')

                    # Honor redirected Desktop known-folder configuration for the interactive user.
                    $desktopReg = "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                    try {
                        $rawDesktop = (Get-ItemProperty -LiteralPath $desktopReg -Name Desktop -ErrorAction Stop).Desktop
                        if ($rawDesktop) {
                            $expandedDesktop = [Environment]::ExpandEnvironmentVariables(
                                $rawDesktop.Replace('%USERPROFILE%', $profile.LocalPath)
                            )
                            $interactiveDesktopCandidates += $expandedDesktop
                        }
                    } catch { }
                }
            } catch {
                Write-Warning "Could not resolve interactive user profile for $accountName. $($_.Exception.Message)"
            }
        }
    }
} catch {
    Write-Warning "Could not inspect the interactive Explorer session. $($_.Exception.Message)"
}

# Also keep the current/elevated account locations as fallbacks.
$userDesktopCandidates = @(
    $interactiveDesktopCandidates
    $WshShell.SpecialFolders.Item('Desktop')
    [Environment]::GetFolderPath('DesktopDirectory')
    $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE 'Desktop' })
    $(if ($env:OneDrive) { Join-Path $env:OneDrive 'Desktop' })
    $(if ($env:OneDriveConsumer) { Join-Path $env:OneDriveConsumer 'Desktop' })
) | Where-Object { $_ } | Select-Object -Unique

$commonDesktopCandidates = @(
    $WshShell.SpecialFolders.Item('AllUsersDesktop'),
    [Environment]::GetFolderPath('CommonDesktopDirectory'),
    (Join-Path $env:PUBLIC 'Desktop')
) | Where-Object { $_ } | Select-Object -Unique

$desktopShortcuts = @()
$desktopFolders = @()
$desktopFolders += @($userDesktopCandidates)
$desktopFolders += @($commonDesktopCandidates)
foreach ($folder in @($desktopFolders | Select-Object -Unique)) {
    $created = New-PlayZoneShortcut $folder
    if ($created) { $desktopShortcuts += $created }
}
if ($desktopShortcuts.Count -lt 1) {
    Fail 'Could not create a verified PlayZone Manager shortcut on any Windows Desktop location.'
}

# Start-menu and all-users Startup shortcuts are separate from the desktop shortcut.
foreach ($folder in @(
    [Environment]::GetFolderPath('CommonPrograms'),
    [Environment]::GetFolderPath('CommonStartup')
) | Where-Object { $_ } | Select-Object -Unique) {
    [void](New-PlayZoneShortcut $folder)
}

$PrimaryDesktopShortcut = $desktopShortcuts[0]
Write-Host "Desktop shortcut ready: $PrimaryDesktopShortcut" -ForegroundColor Green

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

if (-not $NonInteractive) {
    Step 'Opening PlayZone Manager independently from the installer console'
    # Launch the verified .lnk through the Windows shell. Explorer owns the new
    # desktop process, so closing this installer CMD/PowerShell window cannot
    # terminate PlayZone Manager.
    $launched = $false
    try {
        Start-Process -FilePath "$env:WINDIR\explorer.exe" -ArgumentList @('"' + $PrimaryDesktopShortcut + '"')
        $launched = $true
    } catch {
        Write-Warning "Explorer shortcut launch failed. $($_.Exception.Message)"
    }
    if (-not $launched) {
        try {
            $ShellApplication = New-Object -ComObject Shell.Application
            $ShellApplication.ShellExecute($PrimaryDesktopShortcut, '', '', 'open', 1)
            $launched = $true
        } catch {
            Write-Warning "Windows Shell shortcut launch failed. $($_.Exception.Message)"
        }
    }
    if (-not $launched) {
        Write-Warning 'PlayZone Manager was installed successfully but could not be auto-opened. Use the PlayZone Manager desktop shortcut.'
    }
}

Write-Host ''
Write-Host '===================================================' -ForegroundColor Green
Write-Host ' PlayZone Manager installation completed' -ForegroundColor Green
Write-Host '===================================================' -ForegroundColor Green
Write-Host 'Desktop App : PlayZone Manager.exe (embedded Chromium / Electron)'
Write-Host 'Local Web   : http://127.0.0.1:8000 (internal backend only)'
Write-Host 'Voltra TCP  : 10086'
Write-Host "Data        : $DataRoot"
Write-Host "Service log : $DataRoot\logs\service.log"
Write-Host 'Cloud Sync  : DISABLED'
Write-Host 'Internet    : Required once to download Electron unless its runtime ZIP is bundled; otherwise only for Tailscale remote support'
Write-Host 'Remote setup: Run Setup-Tailscale-Support.bat as Administrator after Tailscale is installed'
Write-Host ''
if (-not $NonInteractive) {
    Read-Host 'Press Enter to close'
}
