$ErrorActionPreference = 'Stop'

$Target = 'http://127.0.0.1:8000'
$Health = "$Target/api/health"
$ToolRoot = Join-Path $env:LOCALAPPDATA 'abo_aYmAn\CloudflareTest'
$Cloudflared = Join-Path $ToolRoot 'cloudflared.exe'
$LogFile = Join-Path $ToolRoot 'cloudflared-test.log'
$OutFile = Join-Path $ToolRoot 'cloudflared-test.out.log'
$ProfileRoot = Join-Path $ToolRoot 'profile'
$DownloadUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'

function Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

Write-Host 'abo_aYmAn - Cloudflare Quick Tunnel Test' -ForegroundColor Green
Write-Host 'This test does NOT modify the PlayZone database or Windows Service.'

Step 'Checking local abo_aYmAn backend'
try {
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $Health
    if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
} catch {
    Write-Host 'Local backend is not healthy on http://127.0.0.1:8000' -ForegroundColor Red
    Write-Host 'Start abo_aYmAn first, then run this test again.'
    Read-Host 'Press Enter to close'
    exit 2
}
Write-Host 'Backend: OK' -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $ToolRoot,$ProfileRoot,(Join-Path $ProfileRoot '.cloudflared') | Out-Null

if (-not (Test-Path -LiteralPath $Cloudflared)) {
    Step 'Downloading cloudflared from official Cloudflare GitHub release'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $Cloudflared
}

Step 'Verifying cloudflared'
$version = & $Cloudflared --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Force $Cloudflared -ErrorAction SilentlyContinue
    throw 'cloudflared verification failed.'
}
Write-Host $version -ForegroundColor DarkGray

Remove-Item -Force $LogFile,$OutFile -ErrorAction SilentlyContinue

$oldUserProfile = $env:USERPROFILE
$oldHome = $env:HOME
$env:USERPROFILE = $ProfileRoot
$env:HOME = $ProfileRoot
$process = $null

try {
    Step 'Starting TryCloudflare tunnel'
    $process = Start-Process -FilePath $Cloudflared -ArgumentList @('tunnel','--url',$Target) -PassThru -WindowStyle Hidden -RedirectStandardError $LogFile -RedirectStandardOutput $OutFile

    $remoteUrl = $null
    $deadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { break }
        if (Test-Path -LiteralPath $LogFile) {
            $text = Get-Content -LiteralPath $LogFile -Raw -ErrorAction SilentlyContinue
            $match = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if ($match.Success) {
                $remoteUrl = $match.Value
                break
            }
        }
        Start-Sleep -Milliseconds 300
        $process.Refresh()
    }

    if (-not $remoteUrl) {
        $tail = ''
        if (Test-Path -LiteralPath $LogFile) {
            $tail = (Get-Content -LiteralPath $LogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        Write-Host 'Quick Tunnel did not return a URL.' -ForegroundColor Red
        if ($tail) { Write-Host $tail -ForegroundColor DarkYellow }
        Read-Host 'Press Enter to close'
        exit 3
    }

    try { Set-Clipboard -Value $remoteUrl } catch { }

    Write-Host ''
    Write-Host '===================================================' -ForegroundColor Green
    Write-Host ' Cloudflare Quick Tunnel is READY' -ForegroundColor Green
    Write-Host '===================================================' -ForegroundColor Green
    Write-Host "Remote URL : $remoteUrl" -ForegroundColor Yellow
    Write-Host "Local URL  : $Target"
    Write-Host ''
    Write-Host 'The URL was copied to the clipboard when possible.'
    Write-Host 'On abo_aYmAn Mobile v0.2, add a customer and paste this URL.'
    Write-Host 'Keep this window open while testing. Closing/stopping it disables the URL.'
    Write-Host 'Quick Tunnel is TEST ONLY; the URL is temporary and can change every run.' -ForegroundColor DarkYellow

    Read-Host 'Press Enter to STOP the tunnel'
}
finally {
    $env:USERPROFILE = $oldUserProfile
    $env:HOME = $oldHome
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Write-Host 'Cloudflare Quick Tunnel stopped.' -ForegroundColor Cyan
    }
}
