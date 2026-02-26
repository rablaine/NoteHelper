# NoteHelper

A single-user note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

## Getting Started

### Prerequisites

- **Python 3.13** (must be exactly 3.13 — later versions cause dependency conflicts during install)
- pip and venv
- Azure CLI (`az`) installed and available in your PATH
- Node.js 18+ with npm/npx (optional, required for WorkIQ meeting import feature)

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
```

2. **Create virtual environment:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# or
source venv/bin/activate      # Linux/Mac
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables:**
```bash
cp .env.example .env
# Generate secret key:
python -c "import secrets; print(secrets.token_hex(32))"
# Add the generated key to .env as SECRET_KEY
```

5. **Start the server:**
```bash
python run.py
```

6. **Visit** `http://localhost:5000` in your browser

> **Note:** The database will be created automatically in `data/notehelper.db` on first run.

### Initial Setup (First Run)

After the server is running, you need to connect to MSX and import your data:

1. **Authenticate with Azure:** Run `az login` in your terminal to sign in with your Microsoft account.

2. **Refresh your token:** In the app, click the **Admin** menu (top-right) → **Admin Panel** → **Refresh Token** and then **Test Token** to verify the connection is working.

3. **Import accounts:** Go to **Admin** → **Data Management** → **Import Accounts from MSX**. This pulls in your customer accounts.

4. **Import milestones:** From the same Data Management page, run **Import Milestones** to pull in your milestone data.

5. **Import revenue history:** Go to **Revenue Analyzer** and import revenue data for your accounts.

Once these steps are complete, you're all set — your customer accounts, milestones, and revenue history are loaded and ready to go.

## Running Tests

```powershell
pytest
pytest --cov=app tests/  # with coverage
```

## License

MIT License - see LICENSE file for details

## Contact

For questions or suggestions, please open an issue on GitHub.
