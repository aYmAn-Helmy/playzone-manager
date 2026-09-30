@echo off
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo =====================================================
echo   abo_aYmAn - Complete Uninstaller
echo =====================================================
echo.
choice /C YN /N /M "Delete database, logs and all saved customer data too? [Y/N]: "
if errorlevel 2 goto keepdata
if errorlevel 1 goto removedata

:removedata
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-abo_aYmAn.ps1" -RemoveData
goto done

:keepdata
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-abo_aYmAn.ps1"

:done
echo.
pause
endlocal
