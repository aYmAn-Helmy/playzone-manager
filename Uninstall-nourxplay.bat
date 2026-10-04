@echo off
title nourxplay - Uninstall
cd /d "%~dp0"
call "%~dp0Uninstall-PlayZone-Service.bat" %*
exit /b %errorlevel%
