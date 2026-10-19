@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\benchmark-predictions.ps1" %*
exit /b %ERRORLEVEL%
