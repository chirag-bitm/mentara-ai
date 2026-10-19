@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stt-accuracy.ps1" %*
if errorlevel 1 pause
