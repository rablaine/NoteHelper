@echo off
REM Sales Buddy Uninstall - removes scheduled tasks and stops the server
REM Does NOT delete the app files or database (that's just deleting the folder)
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1"
