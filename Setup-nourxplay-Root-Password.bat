@echo off
title nourxplay - ROOT Password
cd /d "%~dp0"
call "%~dp0Setup-Root-Password.bat"
exit /b %errorlevel%
