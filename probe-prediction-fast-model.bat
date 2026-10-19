@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\probe-prediction-fast-model.ps1"
exit /b %ERRORLEVEL%
