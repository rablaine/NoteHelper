# Desktop App Packaging — MSI Installer + Edge App Mode

## Goal
Let users install NoteHelper like a native desktop app: download an MSI, double-click to install, launch from Start Menu. No terminal, no `flask run`, no Python install required.

## Architecture

```
NoteHelper-Setup.msi
  └─ installs to C:\Program Files\NoteHelper\
      ├── notehelper.exe          ← Tiny launcher (PyInstaller-built)
      ├── python311\              ← Embedded Python (no system install needed)
      │   ├── python.exe
      │   └── Lib\site-packages\ ← All pip deps pre-installed
      ├── app\                    ← Flask app code
      ├── templates\
      ├── static\
      ├── .env.default            ← Default config (copied to AppData on first run)
      └── data\                   ← Empty (DB created at runtime in AppData)

Runtime data lives in:
  %APPDATA%\NoteHelper\
      ├── data\notehelper.db      ← User's database (persists across updates)
      ├── .env                    ← User's config
      └── logs\                   ← App logs
```

## How It Works

### Launcher (`notehelper.exe`)
A small Python script bundled with PyInstaller that:
1. Ensures `%APPDATA%\NoteHelper\` exists, copies default `.env` if first run
2. Sets `DATABASE_URL` to point at the AppData DB path
3. Starts Flask on `localhost:5000` (or first available port) in a background thread
4. Waits for Flask to respond on `/health` (quick self-check)
5. Opens Edge in app mode: `msedge.exe --app=http://localhost:5000 --user-data-dir=%APPDATA%\NoteHelper\edge-profile`
6. Monitors the Edge process — when the user closes the window, shuts down Flask and exits

```python
# Pseudocode for launcher
import subprocess, threading, time, sys, os

def start_flask():
    from app import create_app
    app = create_app()
    app.run(host='127.0.0.1', port=5000)

def main():
    # Start Flask in background thread
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()

    # Wait for Flask to be ready
    wait_for_health("http://127.0.0.1:5000/health")

    # Launch Edge in app mode
    edge = find_edge_executable()
    proc = subprocess.Popen([edge, "--app=http://127.0.0.1:5000"])
    proc.wait()  # Block until user closes the window
    sys.exit(0)  # Flask thread dies with the process
```

### Edge App Mode
- `--app=URL` removes all browser chrome (no tabs, address bar, bookmarks)
- `--user-data-dir=...` gives NoteHelper its own Edge profile (no interference with the user's regular Edge sessions, no "restore tabs" prompts)
- User sees a clean window with just NoteHelper content and a title bar
- Gets its own taskbar icon and Alt+Tab entry
- Right-click context menu still shows "Inspect Element" but users won't notice

### Fallback
If Edge isn't found (unlikely on Windows 10/11), fall back to Chrome with the same `--app` flag. If neither is found, open the default browser to `http://localhost:5000` (degrades to current experience).

## Build Pipeline

### Step 1: Embedded Python Bundle
```powershell
# Download Python embeddable zip (no installer needed)
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.13.x/python-3.13.x-embed-amd64.zip" -OutFile python-embed.zip
Expand-Archive python-embed.zip -DestinationPath build\python

# Install pip into the embedded Python
build\python\python.exe get-pip.py

# Install all dependencies
build\python\python.exe -m pip install -r requirements.txt --target build\python\Lib\site-packages
```

### Step 2: PyInstaller Launcher
```powershell
# Build the launcher exe (one-file mode)
pyinstaller --onefile --windowed --name notehelper --icon static/icon.ico launcher.py
```

`--windowed` prevents a console window from flashing on launch.

### Step 3: MSI with WiX
WiX Toolset v4 builds the MSI. Key features:
- Install to Program Files
- Create Start Menu shortcut
- Register in Add/Remove Programs
- Check for Azure CLI as a prerequisite (warn if missing, don't block)
- Set file associations if desired (e.g., `.notehelper` backup files)

Alternatively, use **MSIX** for a more modern installer that supports auto-update via App Installer.

### Step 4: CI Build Script
```powershell
# Full build (could be a GitHub Action or local script)
scripts/build-installer.ps1
# Outputs: dist/NoteHelper-Setup-1.x.x.msi
```

## Azure CLI / Auth Dependency

- `DefaultAzureCredential` in `gateway_client.py` calls `az` from PATH
- This works as long as Azure CLI is installed — doesn't matter how Python was launched
- MSI installer can check for `az` and display a message if not found
- The onboarding wizard already handles `az login` with the right scope on first use
- No code changes needed to the auth flow

## Database Location Change

Currently the DB lives at `data/notehelper.db` relative to the project root. For an installed app, it needs to live in a user-writable location:

- **Install time:** Create `%APPDATA%\NoteHelper\data\`
- **Launcher:** Set `DATABASE_URL=sqlite:///%APPDATA%/NoteHelper/data/notehelper.db` before starting Flask
- **Migrations:** Run on every launch (already idempotent)
- **Backup/restore:** Update `backup.ps1` / `restore.ps1` to use the AppData path

## Update Strategy

Two options:

### Option A: MSI Replacements
- Ship new MSI for each version
- User downloads and runs it — MSI handles the upgrade (replaces Program Files, leaves AppData alone)
- Simple, familiar, works

### Option B: Auto-Update
- On startup, launcher checks a GitHub release API (or a simple JSON file on blob storage) for the latest version
- If newer, prompt user to download
- Could use MSIX + App Installer for fully automatic updates

Recommendation: Start with Option A, add auto-update later if adoption grows.

## Migration Path from Current Setup

For existing users who run from source:
1. Install the MSI
2. Copy `data/notehelper.db` from their repo folder to `%APPDATA%\NoteHelper\data\`
3. Done — all data preserved

Could automate this with a one-time migration prompt on first launch: "Found an existing NoteHelper database at [path]. Import it?"

## Open Questions

- **Icon:** Need a proper `.ico` file for the exe and Start Menu shortcut
- **Signing:** MSI/exe should be code-signed to avoid SmartScreen warnings. Need a code signing cert (Microsoft internal certs may work)
- **Auto-update:** Worth building from day one, or add later?
- **Name:** The rebrand should happen before building the installer so the MSI, shortcuts, and AppData folder all use the new name

## Prerequisites Summary

What the user needs on their machine:
1. **Windows 10/11** (Edge is already there)
2. **Azure CLI** (for AI features and sharing — most internal users have it)

What they do NOT need:
- Python
- Git
- pip / venv
- A terminal
