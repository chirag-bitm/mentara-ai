@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify.ps1"
set "MENTARA_EXIT_CODE=%ERRORLEVEL%"
if not "%MENTARA_EXIT_CODE%"=="0" pause
exit /b %MENTARA_EXIT_CODE%
