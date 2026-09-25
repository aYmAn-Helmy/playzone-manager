param(
    [Parameter(Mandatory = $true)]
    [string]$Target,

    [int]$ListenPort = 10086,
    [int]$TargetPort = 10086,

    [switch]$ConfigureFirewall
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RelayScript = Join-Path $ScriptDir "tailscale_voltra_relay.py"

if (-not (Test-Path $RelayScript)) {
    throw "Relay script not found: $RelayScript"
}

$Tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $Tailscale) {
    $Tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
}
if (-not $Tailscale) {
    throw "Tailscale CLI was not found. Install Tailscale and connect this PC to the same tailnet first."
}

& $Tailscale.Source status | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Tailscale is installed but not connected."
}

if ($ConfigureFirewall) {
    $ruleName = "PlayZone Voltra Relay TCP $ListenPort"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $ListenPort `
            -RemoteAddress LocalSubnet | Out-Null
        Write-Host "Created Windows Firewall rule '$ruleName' for LocalSubnet only."
    }
}

$Python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
}
if ($Python) {
    & $Python.Source $RelayScript --target $Target --listen-port $ListenPort --target-port $TargetPort
    exit $LASTEXITCODE
}

$PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $PyLauncher) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
}
if ($PyLauncher) {
    & $PyLauncher.Source -3 $RelayScript --target $Target --listen-port $ListenPort --target-port $TargetPort
    exit $LASTEXITCODE
}

throw "Python 3 was not found. Install Python 3 or run the relay on another LAN gateway."
