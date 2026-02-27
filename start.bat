@echo off
REM ==========================================
REM  NoteHelper Launcher (Windows)
REM  Creates venv, installs deps, starts app
REM ==========================================

echo.
echo  NoteHelper Launcher
echo  ====================
echo.

REM -- Locate Python ----------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.13+ and add it to PATH.
    pause
    exit /b 1
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
