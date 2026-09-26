$ErrorActionPreference = 'Stop'

$RuntimeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$Python = Join-Path $RuntimeRoot '.runtime\python\python.exe'
$Backend = Join-Path $RuntimeRoot 'backend'

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot 'logs') | Out-Null

if (-not (Test-Path $Python)) {
    throw "PlayZone portable Python runtime is missing: $Python"
}

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

Set-Location $Backend
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
