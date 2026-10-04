@echo off
title nourxplay - Setup
cd /d "%~dp0"
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-PlayZone-Service.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] Installation failed.
  pause
  exit /b 1
)
