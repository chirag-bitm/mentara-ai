@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\probe-prediction-latency.ps1"
exit /b %ERRORLEVEL%
