@echo off
REM NoteHelper Deploy - pulls latest code, installs deps, restarts server
REM Auto-elevates (admin) only if PORT in .env is below 1024 (e.g. port 80)
cd /d "%~dp0"

set PORT=5000
if exist .env (
    for /f "tokens=1,2 delims==" %%a in (.env) do (
        if "%%a"=="PORT" set PORT=%%b
    )
)

if %PORT% LSS 1024 (
    powershell -Command "Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0start.ps1\" -Force' -Verb RunAs"
) else (
    powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Force
)
