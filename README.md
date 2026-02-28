# NoteHelper

A single-user note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

## Getting Started

### Prerequisites

- **Python 3.13+** (the launcher can install this for you)
- **Azure CLI** (optional — required for MSX and AI features; the launcher can install this too)
- **VPN connection** — required for MSX integration (account imports, milestones)
- Git

### Quick Start

The fastest way to get running — just clone and run `start.bat`. It checks for prerequisites, offers to install anything missing via `winget`, then sets up the app:

```powershell
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
start.bat
```

The script will:
1. Check for Python 3.13+ and Azure CLI — offer to install via `winget` if missing
2. Create a Python virtual environment (if one doesn't exist)
3. Install all dependencies from `requirements.txt`
4. Create a `.env` file with a generated secret key (if one doesn't exist)
5. Start the server on `http://localhost:5000`

On subsequent runs, the script detects the existing venv and `.env`, installs any new dependencies, and launches the app.

> **Note:** Edit `.env` to add your Azure credentials for MSX and AI features. See [AI Features](#ai-features-optional) below.

### Manual Setup

If you prefer to set things up yourself:

1. **Clone the repository:**
```bash
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
```

2. **Create virtual environment:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables:**
```powershell
copy .env.example .env
# Generate a secret key and add it to .env:
python -c "import secrets; print(secrets.token_hex(32))"
```

5. **Start the server:**
```bash
python run.py
```

6. **Visit** `http://localhost:5000` in your browser

> **Note:** The database will be created automatically in `data/notehelper.db` on first run.

### Initial Setup (First Run)

When you first launch NoteHelper, a **guided setup wizard** walks you through connecting your data:

1. **Welcome** — quick overview of NoteHelper and what it does
2. **Authenticate with Azure** — the wizard checks for an existing `az login` session and prompts you to authenticate if needed. This is required for MSX integration (accounts, milestones).
3. **Import Accounts** — pulls your customer accounts from MSX with one click
4. **Import Milestones** — syncs milestone data for your accounts from MSX
5. **Import Revenue Data (optional)** — import a revenue CSV from the ACR Service Level Subscription report to power the Revenue Analyzer (trend charts, service breakdowns, growth tracking)

You can skip steps and come back later — the wizard remembers your progress. Once dismissed, you can re-run it from the **Setup Wizard** button in the navigation bar (appears when no accounts are loaded).

All of these imports can also be run independently from Admin Panel and Revenue Analyzer after initial setup.

## Running Tests

```powershell
pytest
pytest --cov=app tests/  # with coverage
```

## AI Features (Optional)

NoteHelper can use Azure OpenAI to auto-suggest topics, match milestones, and analyze call notes. This requires an Azure OpenAI resource and a service principal for authentication.

### 1. Create an Azure OpenAI Resource

1. In the [Azure Portal](https://portal.azure.com), create an **Azure OpenAI** resource
2. Once deployed, go to **Keys and Endpoint** and copy the **Endpoint** URL (e.g. `https://your-resource.openai.azure.com/`)
3. Go to **Model deployments** → **Manage Deployments** and deploy a model (e.g. `gpt-4o-mini`). Note the **deployment name**

### 2. Create a Service Principal

```bash
# Create the service principal
az ad sp create-for-rbac --name "NoteHelper-AI" --skip-assignment

# Note the output values:
# - appId      → AZURE_CLIENT_ID
# - password   → AZURE_CLIENT_SECRET
# - tenant     → AZURE_TENANT_ID
```

### 3. Grant Permissions on the OpenAI Resource

The service principal needs the **Cognitive Services OpenAI User** role on your Azure OpenAI resource:

```bash
# Get your OpenAI resource ID
az cognitiveservices account show \
  --name your-openai-resource-name \
  --resource-group your-resource-group \
  --query id -o tsv

# Assign the role
az role assignment create \
  --assignee <AZURE_CLIENT_ID> \
  --role "Cognitive Services OpenAI User" \
  --scope <resource-id-from-above>
```

### 4. Add to .env

```dotenv
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_CLIENT_ID=your-app-id
AZURE_CLIENT_SECRET=your-password
AZURE_TENANT_ID=your-tenant-id
```

### 5. Verify in NoteHelper

After restarting the server, AI features are automatically enabled when `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` are configured. The AI-powered "Suggest Topics" button will appear on the call log form.

## Compliance

This application stores customer account data locally. To remain compliant with organizational data handling policies:

- **Must run on a Microsoft-managed device** (Intune-enrolled or domain-joined)
- **Must reside on a BitLocker-encrypted drive**
- Do not copy the database file (`data/notehelper.db`) to unmanaged devices or unencrypted storage

## License

MIT License - see LICENSE file for details

## Contact

For questions or suggestions, please open an issue on GitHub.
