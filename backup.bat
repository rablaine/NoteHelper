@echo off
REM Sales Buddy Backup - runs a manual backup to OneDrive
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\backup.ps1"
