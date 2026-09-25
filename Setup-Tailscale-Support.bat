@echo off
setlocal
cd /d "%~dp0"
title PlayZone - Tailscale Remote Support Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Tailscale-Support.ps1"
exit /b %errorlevel%
