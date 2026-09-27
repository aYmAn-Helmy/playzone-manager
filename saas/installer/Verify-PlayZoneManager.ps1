$ErrorActionPreference = 'Continue'
$InstallRoot = Join-Path $env:ProgramFiles 'PlayZone Manager'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'

Write-Host 'PlayZone Manager verification' -ForegroundColor Cyan
Write-Host ('Desktop EXE : ' + (Test-Path (Join-Path $InstallRoot 'desktop\PlayZoneManager.exe')))
Write-Host ('Python      : ' + (Test-Path (Join-Path $InstallRoot 'runtime\.runtime\python\python.exe')))
Write-Host ('Local DB    : ' + (Test-Path (Join-Path $DataRoot 'playzone.db')))
Write-Host ('Edge DB     : ' + (Test-Path (Join-Path $DataRoot 'edge.db')))

$task = schtasks.exe /Query /TN 'PlayZone Manager Edge' 2>$null
Write-Host ('Startup Task: ' + $(if ($LASTEXITCODE -eq 0) {'OK'} else {'MISSING'}))

try {
    $h = Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:8000/api/health'
    Write-Host ('Local Edge  : ONLINE ' + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
} catch {
    Write-Host ('Local Edge  : OFFLINE - ' + $_.Exception.Message) -ForegroundColor Red
}

try {
    $tcp = New-Object Net.Sockets.TcpClient
    $iar = $tcp.BeginConnect('127.0.0.1',10086,$null,$null)
    $ok = $iar.AsyncWaitHandle.WaitOne(1000)
    if ($ok -and $tcp.Connected) { Write-Host 'Voltra TCP   : LISTENING 10086' -ForegroundColor Green } else { Write-Host 'Voltra TCP   : NOT LISTENING' -ForegroundColor Yellow }
    $tcp.Close()
} catch { Write-Host ('Voltra TCP   : ERROR - ' + $_.Exception.Message) -ForegroundColor Yellow }

Write-Host ('Edge log     : ' + (Join-Path $DataRoot 'logs\edge.log'))
Read-Host 'Press Enter to close'
