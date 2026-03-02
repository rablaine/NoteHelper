@echo off
REM NoteHelper Launcher - double-click to start
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
