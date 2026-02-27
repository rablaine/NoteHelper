#!/usr/bin/env bash
# ==========================================
#  NoteHelper Launcher (Linux / macOS)
#  Creates venv, installs deps, starts app
# ==========================================

set -e

echo ""
echo " NoteHelper Launcher"
echo " ===================="
echo ""

# -- Locate Python ------------------------------------------------------------
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python not found. Install Python 3.13+ and add it to PATH."
    exit 1
fi

echo "[OK] Using $($PYTHON --version 2>&1)"

# -- Create venv if missing ----------------------------------------------------
if [ ! -f "venv/bin/activate" ]; then
    echo "[SETUP] Creating virtual environment..."
    $PYTHON -m venv venv
    echo "[SETUP] Virtual environment created."
else
    echo "[OK] Virtual environment found."
fi

# -- Activate venv -------------------------------------------------------------
source venv/bin/activate

# -- Install / update dependencies ---------------------------------------------
echo "[SETUP] Installing dependencies..."
pip install -r requirements.txt --quiet
echo "[OK] Dependencies installed."

# -- Set up .env if missing ----------------------------------------------------
if [ ! -f ".env" ]; then
    echo "[SETUP] Creating .env from .env.example..."
    cp .env.example .env
    # Generate a random SECRET_KEY
    NEW_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
    # Replace the placeholder key in the new .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/your-secret-key-here-change-in-production/$NEW_KEY/" .env
    else
        sed -i "s/your-secret-key-here-change-in-production/$NEW_KEY/" .env
    fi
    echo "[SETUP] .env created with generated SECRET_KEY."
    echo "[SETUP] Edit .env to add your Azure credentials if needed."
    echo ""
fi

# -- Launch the app ------------------------------------------------------------
echo "[START] Starting NoteHelper on http://localhost:5000 ..."
echo "        Press Ctrl+C to stop."
echo ""
python run.py
