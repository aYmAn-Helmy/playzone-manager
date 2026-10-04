@echo off
title nourxplay - Remote Support
cd /d "%~dp0"
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Tailscale-Support.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] Tailscale Remote Support setup failed.
  pause
  exit /b 1
)
