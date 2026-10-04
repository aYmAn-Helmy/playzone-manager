#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$InstallRoot = if (Test-Path (Join-Path $PSScriptRoot '.runtime\python\python.exe')) { $PSScriptRoot } else { Join-Path $env:ProgramFiles 'PlayZone Manager' }
$Python = Join-Path $InstallRoot '.runtime\python\python.exe'
$DataRoot = Join-Path $env:ProgramData 'PlayZone Manager'
$SecureDataRoot = Join-Path $DataRoot 'secure-data'
$env:PLAYZONE_DB_PATH = Join-Path $SecureDataRoot 'playzone.db'

if (-not (Test-Path -LiteralPath $Python)) {
    throw "nourxplay runtime not found. Install nourxplay first: $Python"
}

Write-Host 'nourxplay v0.35.0 - ROOT Password Setup' -ForegroundColor Cyan
Write-Host 'This resets the ROOT password locally and invalidates existing ROOT login tokens.'

while ($true) {
    $secure1 = Read-Host 'Enter new ROOT password (minimum 12 characters)' -AsSecureString
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
        if ($LASTEXITCODE -ne 0) { throw 'ROOT password setup failed.' }
        Write-Host 'ROOT password updated successfully.' -ForegroundColor Green
        break
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
        $plain1 = $null
        $plain2 = $null
    }
}

Read-Host 'Press Enter to close'
