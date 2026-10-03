@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Control-Checker.ps1" -Action Start
if errorlevel 1 (
  pause
) else (
  start "" "http://127.0.0.1:8095/"
)
endlocal
