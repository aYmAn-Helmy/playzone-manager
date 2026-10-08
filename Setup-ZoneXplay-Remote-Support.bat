@echo off
title ZoneXplay - Remote Support
cd /d "%~dp0"
call "%~dp0Setup-Tailscale-Support.bat"
exit /b %errorlevel%
