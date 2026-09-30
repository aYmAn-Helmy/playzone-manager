$ErrorActionPreference = 'SilentlyContinue'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DesktopRuntime = Join-Path $InstallRoot 'desktop-runtime'
$DesktopExe = Join-Path $DesktopRuntime 'abo_aYmAn.exe'
$DesktopShell = Join-Path $InstallRoot 'desktop-shell'
$Health = 'http://127.0.0.1:8000/api/health'

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 $Health
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Path -LiteralPath $DesktopExe)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "abo_aYmAn Desktop runtime is missing. Re-run Install-PlayZone-Service.bat to repair it.",
        'abo_aYmAn', 'OK', 'Error'
    ) | Out-Null
    exit 2
}

Start-Process -FilePath $DesktopExe -ArgumentList @('"' + $DesktopShell + '"') -WorkingDirectory $DesktopRuntime
