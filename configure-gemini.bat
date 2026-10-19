@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure-gemini.ps1"
if errorlevel 1 pause
