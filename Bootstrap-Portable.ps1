param(
    [string]$PayloadRoot = (Join-Path $PSScriptRoot 'offline-runtime')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = $PSScriptRoot
$Log = Join-Path $Root 'Bootstrap-Portable.log'
$PyVersion = '3.12.6'
$RuntimeRoot = Join-Path $Root '.runtime'
$Runtime = Join-Path $RuntimeRoot 'python'
$Extract = Join-Path $RuntimeRoot 'extract-python'
$Python = Join-Path $Runtime 'python.exe'
$PythonZip = Join-Path $PayloadRoot 'python-3.12.6-embed-amd64.zip'
$GetPip = Join-Path $PayloadRoot 'get-pip.py'
$Wheels = Join-Path $PayloadRoot 'wheels'
$Requirements = Join-Path $PayloadRoot 'requirements-offline.txt'
$Pth = Join-Path $Runtime 'python312._pth'
$Ready = Join-Path $RuntimeRoot 'READY-v0.31-remote-support.txt'

function Write-Step([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath $Log -Value $Message -Encoding UTF8
}

function Invoke-Logged([string]$Exe, [string[]]$CommandArgs) {
    $line = '> ' + $Exe + ' ' + ($CommandArgs -join ' ')
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
    & $Exe @CommandArgs 2>&1 | ForEach-Object {
        Write-Host $_
        Add-Content -LiteralPath $Log -Value ([string]$_) -Encoding UTF8
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Exe"
    }
}

function Assert-OfflinePayload {
    foreach ($required in @($PythonZip,$GetPip,$Requirements,$Wheels)) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Offline runtime payload is incomplete. Missing: $required"
        }
    }
    if ((Get-Item -LiteralPath $PythonZip).Length -lt 8000000) {
        throw 'Bundled Python archive is unexpectedly small.'
    }
    if ((Get-Item -LiteralPath $GetPip).Length -lt 1000000) {
        throw 'Bundled get-pip.py is unexpectedly small.'
    }
    $wheelCount = @(Get-ChildItem -LiteralPath $Wheels -Filter '*.whl' -File).Count
    if ($wheelCount -lt 20) {
        throw "Offline wheel set is incomplete. Found only $wheelCount wheel(s)."
    }

    $criticalWheelPatterns = @(
        'fastapi-*.whl',
        'starlette-*.whl',
        'pydantic-*.whl',
        'pydantic_core-*.whl',
        'typing_extensions-*.whl',
        'typing_inspection-*.whl',
        'annotated_types-*.whl',
        'annotated_doc-*.whl',
        'uvicorn-*.whl',
        'sqlalchemy-*.whl',
        'greenlet-*.whl',
        'httpx-*.whl',
        'httpcore-*.whl',
        'h11-*.whl',
        'anyio-*.whl',
        'idna-*.whl',
        'certifi-*.whl',
        'argon2_cffi-*.whl',
        'argon2_cffi_bindings-*.whl',
        'cffi-*.whl',
        'pycparser-*.whl',
        'pywin32-*.whl',
        'tzdata-*.whl',
        'click-*.whl',
        'pip-*.whl'
    )
    foreach ($pattern in $criticalWheelPatterns) {
        if (-not (Get-ChildItem -LiteralPath $Wheels -Filter $pattern -File | Select-Object -First 1)) {
            throw "Offline runtime payload is incomplete. Missing wheel matching: $pattern"
        }
    }
}

try {
    Set-Content -LiteralPath $Log -Value ("PlayZone Offline Bootstrap v0.31 Remote Support - " + (Get-Date).ToString('s')) -Encoding UTF8
    Assert-OfflinePayload

    if (Test-Path -LiteralPath $Python) {
        try {
            & $Python -c "import fastapi,uvicorn,sqlalchemy,pydantic,httpx,argon2,tzdata,win32serviceutil; print('runtime-ok')" *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Step '[OK] Offline Python runtime is already prepared.'
                exit 0
            }
        }
        catch { }
        Write-Step '[WARN] Existing runtime is incomplete. Rebuilding it from bundled files.'
    }

    if (Test-Path -LiteralPath $Runtime) { Remove-Item -LiteralPath $Runtime -Recurse -Force }
    if (Test-Path -LiteralPath $Extract) { Remove-Item -LiteralPath $Extract -Recurse -Force }
    New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
    New-Item -ItemType Directory -Path $Extract -Force | Out-Null

    Write-Step '[1/5] Extracting bundled Python 3.12.6 x64 runtime...'
    Expand-Archive -LiteralPath $PythonZip -DestinationPath $Extract -Force
    $py = Get-ChildItem -LiteralPath $Extract -Filter 'python.exe' -File -Recurse | Select-Object -First 1
    if ($null -eq $py) { throw 'python.exe was not found inside the bundled Python archive.' }
    Copy-Item -Path (Join-Path $py.Directory.FullName '*') -Destination $Runtime -Recurse -Force
    if (-not (Test-Path -LiteralPath $Python)) { throw 'python.exe was not created in .runtime\python.' }

    Write-Step '[2/5] Configuring isolated Python paths...'
    New-Item -ItemType Directory -Path (Join-Path $Runtime 'Lib\site-packages') -Force | Out-Null
    @(
        'python312.zip'
        '.'
        'Lib'
        'Lib\site-packages'
        '..\..\backend'
        'import site'
    ) | Set-Content -LiteralPath $Pth -Encoding ASCII

    $check = & $Python -c "import sys; print('PLAYZONE_OFFLINE_PYTHON_OK'); print(sys.version); print(sys.executable)" 2>&1
    $checkExit = $LASTEXITCODE
    $check | ForEach-Object { Write-Host $_; Add-Content -LiteralPath $Log -Value ([string]$_) -Encoding UTF8 }
    if ($checkExit -ne 0 -or (($check -join "`n") -notmatch 'PLAYZONE_OFFLINE_PYTHON_OK')) {
        throw "Bundled Python did not start correctly. Exit code: $checkExit"
    }

    Write-Step '[3/5] Installing bundled pip locally (no Internet)...'
    Invoke-Logged $Python @($GetPip, '--no-index', '--find-links', $Wheels, '--disable-pip-version-check', '--no-warn-script-location')

    Write-Step '[4/5] Installing bundled PlayZone dependencies (no Internet)...'
    Invoke-Logged $Python @('-m','pip','install','--no-index','--find-links',$Wheels,'--disable-pip-version-check','--no-warn-script-location','-r',$Requirements)

    Write-Step '[5/5] Verifying complete PlayZone runtime...'
    Invoke-Logged $Python @('-c', "import fastapi,uvicorn,sqlalchemy,pydantic,httpx,argon2,tzdata,win32serviceutil,win32service,servicemanager; print('PlayZone offline runtime OK')")

    New-Item -ItemType Directory -Path (Join-Path $Root 'data') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root 'logs') -Force | Out-Null
    Set-Content -LiteralPath $Ready -Value "PlayZone Offline Runtime $PyVersion ready" -Encoding ASCII
    Remove-Item -LiteralPath $Extract -Recurse -Force -ErrorAction SilentlyContinue

    Write-Step '[OK] PlayZone offline runtime is ready. No Internet was used by this bootstrap.'
    exit 0
}
catch {
    $msg = $_.Exception.Message
    Write-Host ''
    Write-Host '[ERROR] Offline bootstrap failed:' -ForegroundColor Red
    Write-Host $msg -ForegroundColor Red
    Add-Content -LiteralPath $Log -Value ('[ERROR] ' + $msg) -Encoding UTF8
    Add-Content -LiteralPath $Log -Value $_.ScriptStackTrace -Encoding UTF8
    exit 1
}
