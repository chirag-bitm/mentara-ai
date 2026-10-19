@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\m5-checkpoint.ps1"
if errorlevel 1 pause
