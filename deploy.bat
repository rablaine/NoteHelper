@echo off
REM NoteHelper Deploy - runs start.ps1 -Force with admin elevation
powershell -Command "Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0start.ps1\" -Force' -Verb RunAs"
