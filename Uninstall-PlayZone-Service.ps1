#Requires -RunAsAdministrator
param([switch]$RemoveData)
$target = Join-Path $PSScriptRoot 'Uninstall-abo_aYmAn.ps1'
if (-not (Test-Path -LiteralPath $target)) { throw "Missing uninstaller: $target" }
if ($RemoveData) { & $target -RemoveData } else { & $target }
exit $LASTEXITCODE
