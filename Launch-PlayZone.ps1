$ErrorActionPreference = 'SilentlyContinue'
$Url = 'http://127.0.0.1:8000'
$Health = "$Url/api/health"

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 $Health
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "PlayZone Manager service is not ready. Check C:\ProgramData\PlayZone Manager\logs\service.log",
        'PlayZone Manager', 'OK', 'Error'
    ) | Out-Null
    exit 1
}

$edgeCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { $_ -and (Test-Path $_) }

$edge = $edgeCandidates | Select-Object -First 1
if (-not $edge) {
    $cmd = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($cmd) { $edge = $cmd.Source }
}

if ($edge) {
    Start-Process -FilePath $edge -ArgumentList @('--app=' + $Url, '--start-maximized')
} else {
    Start-Process $Url
}
