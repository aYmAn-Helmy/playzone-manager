$ErrorActionPreference = 'Continue'
$ServiceName='PlayZoneManager'
$DataRoot=Join-Path $env:ProgramData 'nourxplay'
Write-Host 'nourxplay Service Verification' -ForegroundColor Cyan
$svc=Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
Write-Host ('Service      : ' + $(if($svc){$svc.Status}else{'MISSING'}))
try {
    $h=Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:8000/api/health'
    Write-Host ('Local Web    : OK ' + ($h|ConvertTo-Json -Compress)) -ForegroundColor Green
} catch { Write-Host ('Local Web    : FAIL - '+$_.Exception.Message) -ForegroundColor Red }
try {
    $c=New-Object Net.Sockets.TcpClient
    $iar=$c.BeginConnect('127.0.0.1',10086,$null,$null)
    $ok=$iar.AsyncWaitHandle.WaitOne(1500) -and $c.Connected
    $c.Close()
    Write-Host ('Voltra 10086 : ' + $(if($ok){'LISTENING'}else{'NOT LISTENING'}))
} catch { Write-Host ('Voltra 10086 : ERROR - '+$_.Exception.Message) }
Write-Host ('Database     : ' + (Join-Path $DataRoot 'playzone.db'))
Write-Host ('Service log  : ' + (Join-Path $DataRoot 'logs\service.log'))
