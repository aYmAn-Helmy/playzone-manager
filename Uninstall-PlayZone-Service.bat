@echo off
setlocal
title nourxplay - Uninstall

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting administrator privileges...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

if not exist "%~dp0Uninstall-PlayZone-Service.ps1" (
  echo.
  echo [ERROR] Uninstall-PlayZone-Service.ps1 was not found beside this file.
  echo Keep both uninstall files in the same folder and try again.
  echo.
  pause
  exit /b 1
)

echo.
echo nourxplay - Uninstaller
echo ==============================
echo.
echo By default, financial data and backups are preserved.
echo To remove protected data too, run:
echo   Uninstall-nourxplay.bat /RemoveData
echo.

set "EXTRA_ARGS="
if /I "%~1"=="/RemoveData" set "EXTRA_ARGS=-RemoveData"
if /I "%~1"=="/RemoveTailscale" set "EXTRA_ARGS=-RemoveTailscale"
if /I "%~1"=="/RemoveAll" set "EXTRA_ARGS=-RemoveData -RemoveTailscale"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-PlayZone-Service.ps1" %EXTRA_ARGS%
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" (
  echo [ERROR] Uninstall failed with exit code %RC%.
) else (
  echo nourxplay uninstall completed.
)
pause
exit /b %RC%
