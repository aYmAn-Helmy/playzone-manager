$ErrorActionPreference = 'Stop'

$RuntimeRoot = Join-Path $env:ProgramFiles 'PlayZone Manager\runtime'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$Python = Join-Path $RuntimeRoot '.runtime\python\python.exe'
$Backend = Join-Path $RuntimeRoot 'backend'
$Logs = Join-Path $DataRoot 'logs'
$Log = Join-Path $Logs 'edge.log'

New-Item -ItemType Directory -Force -Path $DataRoot,$Logs | Out-Null

if (-not (Test-Path $Python)) {
    Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format o)] ERROR Portable Python missing: $Python"
    exit 2
}

$Pth = Join-Path $RuntimeRoot '.runtime\python\python312._pth'
if (Test-Path $Pth) {
    $PthLines = @(Get-Content -LiteralPath $Pth)
    if ($PthLines -notcontains '..\..\backend') {
        $PthLines += '..\..\backend'
        Set-Content -LiteralPath $Pth -Value $PthLines -Encoding ASCII
    }
}

try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 'http://127.0.0.1:8000/api/health' | Out-Null
    exit 0
} catch { }

$env:PLAYZONE_DB_PATH = Join-Path $DataRoot 'playzone.db'
$env:PLAYZONE_EDGE_DB_PATH = Join-Path $DataRoot 'edge.db'
$env:VOLTRA_DATA_PATH = Join-Path $DataRoot 'voltra.json'
$env:VOLTRA_BASE_URL = 'http://127.0.0.1:8086'
$env:VOLTRA_EMBEDDED = '1'
$env:VOLTRA_DEMO = '0'
$env:VOLTRA_TCP_PORT = '10086'
$env:VOLTRA_HTTP_PORT = '8086'
$env:VOLTRA_POLL_INTERVAL = '10'
$env:VOLTRA_RESPONSE_TIMEOUT = '3'
$env:PLAYZONE_EDGE_APP_VERSION = '0.28-saas-prototype'
$env:PLAYZONE_EDGE_SYNC_INTERVAL = '5'
$env:PYTHONUNBUFFERED = '1'

Set-Location $Backend
Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format o)] Starting PlayZone Edge"
try {
    # Uvicorn writes normal INFO output to stderr. Merge the native streams in
    # cmd.exe so Windows PowerShell 5.1 does not turn them into terminating errors.
    $CommandLine = "`"$Python`" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> `"$Log`" 2>&1"
    & $env:ComSpec /d /s /c $CommandLine
    $exitCode = $LASTEXITCODE
} catch {
    $exitCode = 1
    $Details = ($_ | Out-String).Trim()
    Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format o)] ERROR Failed to launch Edge: $Details"
}
Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format o)] Edge stopped, exit=$exitCode"
exit $exitCode
