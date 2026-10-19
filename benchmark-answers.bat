@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\benchmark-answers.ps1" %*
exit /b %ERRORLEVEL%
