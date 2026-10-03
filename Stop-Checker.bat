@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Control-Checker.ps1" -Action Stop
if errorlevel 1 pause
endlocal
