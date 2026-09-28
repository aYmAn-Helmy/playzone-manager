#Requires -RunAsAdministrator
param(
    [string]$Tag = ''
)

$ErrorActionPreference = 'Stop'

function Find-Tailscale {
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe') }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Tailscale\tailscale.exe') }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Invoke-Tailscale([string[]]$Arguments) {
    & $exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Tailscale command failed (exit $LASTEXITCODE): tailscale $($Arguments -join ' ')"
    }
}

$exe = Find-Tailscale
if (-not $exe) {
    throw 'Tailscale is not installed. Install Tailscale first, then run this setup again.'
}

Write-Host 'PlayZone Manager v0.31 - Tailscale Remote Support Setup' -ForegroundColor Cyan
Write-Host 'The PlayZone backend remains bound to 127.0.0.1:8000.'
Write-Host 'This script enables private Tailscale Serve only; it does not enable Funnel.'

& sc.exe config Tailscale start= auto | Out-Null
& sc.exe failure Tailscale reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null
& sc.exe failureflag Tailscale 1 | Out-Null
Start-Service Tailscale -ErrorAction SilentlyContinue

$rawName = ('playzone-' + $env:COMPUTERNAME.ToLower())
$hostName = ($rawName -replace '[^a-z0-9-]', '-').Trim('-')
if ($hostName.Length -gt 63) { $hostName = $hostName.Substring(0,63).TrimEnd('-') }

$up = @('up','--unattended=true','--accept-dns=false','--accept-routes=false',("--hostname=$hostName"))
if ($Tag) { $up += "--advertise-tags=$Tag" }

Write-Host "`n[1/3] Connecting this PC to Tailscale..." -ForegroundColor Yellow
Write-Host 'If Tailscale asks for browser authorization, complete it once.'
Invoke-Tailscale $up

Write-Host "`n[2/3] Enabling private HTTPS Remote Support with Tailscale Serve..." -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:8000/api/health'
    if ($health.StatusCode -ne 200) { throw 'PlayZone local backend is not healthy on 127.0.0.1:8000.' }
    Invoke-Tailscale @('serve','--bg','--yes','--https=443','http://127.0.0.1:8000')
}
catch {
    Write-Host ''
    Write-Host 'Tailscale is connected, but Serve could not be enabled automatically.' -ForegroundColor Yellow
    Write-Host 'Your tailnet may require one-time HTTPS/Serve approval. Complete the Tailscale prompt, then run this script again.' -ForegroundColor Yellow
    throw
}

Write-Host "`n[3/3] Remote Support status" -ForegroundColor Yellow
& $exe status
Write-Host ''
& $exe serve status

try {
    $status = (& $exe status --json | ConvertFrom-Json)
    $dns = $status.Self.DNSName
    if ($dns) {
        $dns = $dns.TrimEnd('.')
        Write-Host ''
        Write-Host ('Remote URL: https://' + $dns) -ForegroundColor Green
    }
} catch { }

Write-Host ''
Write-Host 'Remote Support is available only inside the tailnet and remains active after restart.' -ForegroundColor Green
Write-Host 'To disable it later, use the ROOT page or run: tailscale serve --https=443 off'
Read-Host 'Press Enter to close'
