@echo off
title nourxplay - Setup
cd /d "%~dp0"
call "%~dp0Install-PlayZone-Service.bat"
exit /b %errorlevel%
