$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = $PSScriptRoot
$Log = Join-Path $Root 'Tailscale-Support-Setup.log'
$Tag = if ($env:PLAYZONE_TAILSCALE_TAG) { $env:PLAYZONE_TAILSCALE_TAG } else { 'tag:playzone-client' }

function Write-Step([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath $Log -Value $Message -Encoding UTF8
}

function Is-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Tailscale {
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        $candidate = Join-Path $base 'Tailscale\tailscale.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Get-LatestTailscaleMsi {
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) {
        'ARM64' { 'arm64' }
        'x86' { 'x86' }
        default { 'amd64' }
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $html = (Invoke-WebRequest -UseBasicParsing -Uri 'https://pkgs.tailscale.com/stable/' -TimeoutSec 60).Content
    $pattern = 'tailscale-setup-([0-9]+\.[0-9]+\.[0-9]+)-' + [regex]::Escape($arch) + '\.msi'
    $matches = [regex]::Matches($html, $pattern)
    if ($matches.Count -eq 0) { throw "Could not find the latest Tailscale $arch MSI package." }
    $versions = $matches | ForEach-Object { [pscustomobject]@{ Name=$_.Value; Version=[version]$_.Groups[1].Value } } | Sort-Object Version -Descending
    return "https://pkgs.tailscale.com/stable/$($versions[0].Name)"
}

try {
    Set-Content -LiteralPath $Log -Value ("PlayZone Tailscale support setup - " + (Get-Date).ToString('s')) -Encoding UTF8

    if (-not (Is-Admin)) {
        Write-Host 'Administrator permission is required. Opening UAC prompt...'
        $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
        Start-Process powershell.exe -Verb RunAs -ArgumentList ($args -join ' ')
        exit 0
    }

    $tailscale = Find-Tailscale
    if (-not $tailscale) {
        Write-Step '[1/4] Downloading the latest stable Tailscale MSI...'
        $url = Get-LatestTailscaleMsi
        $msi = Join-Path $env:TEMP 'playzone-tailscale.msi'
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $msi -TimeoutSec 180
        Write-Step '[2/4] Installing Tailscale silently...'
        $proc = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @('/i',('"' + $msi + '"'),'/qn','/norestart')
        Remove-Item -LiteralPath $msi -Force -ErrorAction SilentlyContinue
        if ($proc.ExitCode -notin @(0,3010)) { throw "Tailscale installer failed with exit code $($proc.ExitCode)." }
        Start-Sleep -Seconds 3
        $tailscale = Find-Tailscale
        if (-not $tailscale) { throw 'Tailscale was installed but tailscale.exe was not found.' }
    } else {
        Write-Step '[1/4] Tailscale is already installed.'
    }

    Write-Step '[3/4] Registering this PlayZone PC for always-on remote support...'
    Write-Host ''
    Write-Host 'Paste a ONE-OFF, PRE-APPROVED auth key tagged for PlayZone support.' -ForegroundColor Cyan
    Write-Host 'The key is used only now and is NOT saved by PlayZone.' -ForegroundColor DarkGray
    $secure = Read-Host 'Tailscale auth key' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $authKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if (-not $authKey -or -not $authKey.StartsWith('tskey-')) { throw 'A valid Tailscale auth key is required.' }

    $name = ('playzone-' + $env:COMPUTERNAME.ToLower()) -replace '[^a-z0-9-]','-'
    if ($name.Length -gt 63) { $name = $name.Substring(0,63).TrimEnd('-') }

    & $tailscale up --auth-key=$authKey --unattended=true --accept-dns=false --accept-routes=false --hostname=$name --advertise-tags=$Tag
    if ($LASTEXITCODE -ne 0) { throw "tailscale up failed with exit code $LASTEXITCODE." }
    Remove-Variable authKey -ErrorAction SilentlyContinue

    Write-Step '[4/4] Verifying connection...'
    & $tailscale status
    if ($LASTEXITCODE -ne 0) { throw 'Tailscale status check failed.' }

    Write-Host ''
    Write-Host '[OK] Tailscale remote support is Always-On and will remain available after restart/logoff.' -ForegroundColor Green
    Write-Host 'Open PlayZone as ROOT to see connection status and support IP.'
    Read-Host 'Press Enter to close'
    exit 0
}
catch {
    $msg = $_.Exception.Message
    Add-Content -LiteralPath $Log -Value ('[ERROR] ' + $msg) -Encoding UTF8
    Write-Host ''
    Write-Host ('[ERROR] ' + $msg) -ForegroundColor Red
    Write-Host ('See log: ' + $Log)
    Read-Host 'Press Enter to close'
    exit 1
}
