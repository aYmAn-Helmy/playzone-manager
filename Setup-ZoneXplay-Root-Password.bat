@echo off
title ZoneXplay - ROOT Password
cd /d "%~dp0"
call "%~dp0Setup-Root-Password.bat"
exit /b %errorlevel%
