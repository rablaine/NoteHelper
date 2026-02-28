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

REM -- Check winget (needed for auto-install) ---------------------------------
set "HAS_WINGET=0"
where winget >nul 2>&1
if %ERRORLEVEL% equ 0 set "HAS_WINGET=1"

REM -- Check Python -----------------------------------------------------------
set "NEED_PYTHON=0"
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    set "NEED_PYTHON=1"
) else (
    REM Python exists — check version
    for /f "delims=" %%V in ('python -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))"') do set "PY_VER=%%V"
    for /f "tokens=1,2 delims=." %%A in ("!PY_VER!") do (
        set "PY_MAJOR=%%A"
        set "PY_MINOR=%%B"
    )
    set "PY_OK=0"
    if !PY_MAJOR! gtr 3 set "PY_OK=1"
    if !PY_MAJOR! equ 3 if !PY_MINOR! geq 13 set "PY_OK=1"
    if "!PY_OK!"=="0" set "NEED_PYTHON=2"
)

if "!NEED_PYTHON!"=="1" (
    echo [ERROR] Python not found.
    echo.
    if "!HAS_WINGET!"=="1" (
        set /p "INSTALL_PY=         Install Python 3.13 automatically? (Y/N): "
        if /i "!INSTALL_PY!"=="Y" (
            echo.
            echo [SETUP] Installing Python 3.13 via winget...
            winget install Python.Python.3.13 --accept-package-agreements --accept-source-agreements
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] Python installation failed.
                pause
                exit /b 1
            )
            echo.
            echo [SETUP] Python installed. Please CLOSE and RE-OPEN this window,
            echo         then run start.bat again so Python is on your PATH.
            echo.
            pause
            exit /b 0
        ) else (
            echo.
            echo         Install Python 3.13+ from: https://www.python.org/downloads/
            echo         Make sure to check "Add Python to PATH" during install.
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo         Install Python 3.13+ from: https://www.python.org/downloads/
        echo         Make sure to check "Add Python to PATH" during install.
        echo.
        pause
        exit /b 1
    )
)

if "!NEED_PYTHON!"=="2" (
    echo [ERROR] Python !PY_VER! found, but 3.13 or later is required.
    echo.
    if "!HAS_WINGET!"=="1" (
        set /p "INSTALL_PY=         Install Python 3.13 alongside your current version? (Y/N): "
        if /i "!INSTALL_PY!"=="Y" (
            echo.
            echo [SETUP] Installing Python 3.13 via winget...
            winget install Python.Python.3.13 --accept-package-agreements --accept-source-agreements
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] Python installation failed.
                pause
                exit /b 1
            )
            echo.
            echo [SETUP] Python 3.13 installed. Please CLOSE and RE-OPEN this window,
            echo         then run start.bat again so the new version is on your PATH.
            echo.
            pause
            exit /b 0
        ) else (
            echo         Download Python 3.13+ from: https://www.python.org/downloads/
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo         Download Python 3.13+ from: https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
)
echo [OK] Python !PY_VER! found.

REM -- Check Azure CLI --------------------------------------------------------
where az >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Azure CLI (az) not found.
    echo.
    echo           The Azure CLI is required for MSX account imports,
    echo           milestone sync, and AI features.
    echo.
    if "!HAS_WINGET!"=="1" (
        set /p "INSTALL_AZ=          Install Azure CLI automatically? (Y/N): "
        if /i "!INSTALL_AZ!"=="Y" (
            echo.
            echo [SETUP] Installing Azure CLI via winget...
            winget install Microsoft.AzureCLI --accept-package-agreements --accept-source-agreements
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] Azure CLI installation failed.
                echo         Install manually from: https://aka.ms/installazurecliwindows
                echo.
            ) else (
                echo [OK] Azure CLI installed.
                echo     Note: You may need to restart this window for 'az' to be available.
                echo.
            )
        ) else (
            echo.
            echo           You can install it later from: https://aka.ms/installazurecliwindows
            echo           NoteHelper will still run, but Azure features won't work.
            echo.
        )
    ) else (
        echo           Install it from: https://aka.ms/installazurecliwindows
        echo           You can still run NoteHelper without it, but Azure
        echo           features will not work until az is installed.
        echo.
        set /p "CONTINUE=          Continue anyway? (Y/N): "
        if /i not "!CONTINUE!"=="Y" exit /b 1
        echo.
    )
)

REM -- Check Node.js (optional — needed for WorkIQ meeting import) -----------
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Node.js not found.
    echo.
    echo           Node.js 18+ is required for WorkIQ meeting import
    echo           ^(Import from Meeting, Auto-fill^). NoteHelper will
    echo           still run, but meeting import features won't work.
    echo.
    if "!HAS_WINGET!"=="1" (
        set /p "INSTALL_NODE=          Install Node.js automatically? (Y/N): "
        if /i "!INSTALL_NODE!"=="Y" (
            echo.
            echo [SETUP] Installing Node.js LTS via winget...
            winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] Node.js installation failed.
                echo         Install manually from: https://nodejs.org/
                echo.
            ) else (
                echo [OK] Node.js installed.
                echo     Note: You may need to restart this window for 'node' to be available.
                echo.
            )
        ) else (
            echo.
            echo           You can install it later from: https://nodejs.org/
            echo           Meeting import features won't work until Node.js is installed.
            echo.
        )
    ) else (
        echo           Install it from: https://nodejs.org/
        echo           Meeting import features won't work until Node.js is installed.
        echo.
    )
) else (
    for /f "delims=" %%V in ('node -v') do echo [OK] Node.js %%V found.
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
