@echo off
title ZoneXplay - Setup
cd /d "%~dp0"
call "%~dp0Install-PlayZone-Service.bat"
exit /b %errorlevel%
