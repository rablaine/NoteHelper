@echo off
setlocal enabledelayedexpansion
REM ==========================================
REM  NoteHelper Launcher (Windows)
REM  Creates venv, installs deps, starts app
REM ==========================================

echo.
echo  NoteHelper Launcher
echo  ====================
echo.

REM -- Check Python -----------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found.
    echo.
    echo         NoteHelper requires Python 3.13 or later.
    echo         Download it from: https://www.python.org/downloads/
    echo.
    echo         Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM -- Check Python version ---------------------------------------------------
for /f "delims=" %%V in ('python -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))"') do set "PY_VER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set "PY_MAJOR=%%A"
    set "PY_MINOR=%%B"
)

set "PY_OK=0"
if %PY_MAJOR% gtr 3 set "PY_OK=1"
if %PY_MAJOR% equ 3 if %PY_MINOR% geq 13 set "PY_OK=1"

if "%PY_OK%"=="0" (
    echo [ERROR] Python %PY_VER% found, but 3.13 or later is required.
    echo.
    echo         Download the latest version from: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [OK] Python %PY_VER% found.

REM -- Check Azure CLI --------------------------------------------------------
where az >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Azure CLI (az) not found.
    echo.
    echo           The Azure CLI is required for MSX account imports,
    echo           milestone sync, and AI features.
    echo.
    echo           Install it from: https://aka.ms/installazurecliwindows
    echo.
    echo           You can still run NoteHelper without it, but Azure
    echo           features will not work until az is installed.
    echo.
    set /p "CONTINUE=Continue anyway? (Y/N): "
    if /i not "!CONTINUE!"=="Y" exit /b 1
    echo.
)

REM -- Create venv if missing -------------------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [SETUP] Virtual environment created.
) else (
    echo [OK] Virtual environment found.
)

REM -- Activate venv ----------------------------------------------------------
call venv\Scripts\activate.bat

REM -- Install / update dependencies ------------------------------------------
echo [SETUP] Installing dependencies...
pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install dependencies. Check requirements.txt.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

REM -- Set up .env if missing -------------------------------------------------
if not exist ".env" (
    echo [SETUP] Creating .env from .env.example...
    copy .env.example .env >nul
    REM Generate a random SECRET_KEY
    for /f "delims=" %%K in ('python -c "import secrets; print(secrets.token_hex(32))"') do set "NEW_KEY=%%K"
    REM Replace the placeholder key in the new .env
    python -c "import pathlib; p=pathlib.Path('.env'); t=p.read_text(); p.write_text(t.replace('your-secret-key-here-change-in-production', '%NEW_KEY%'))"
    echo [SETUP] .env created with generated SECRET_KEY.
    echo [SETUP] Edit .env to add your Azure credentials if needed.
    echo.
)

REM -- Launch the app ---------------------------------------------------------
echo [START] Starting NoteHelper on http://localhost:5000 ...
echo         Press Ctrl+C to stop.
echo.
python run.py
