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

> **Note:** When AI environment variables are not configured, all AI buttons (Auto-tag with AI, Match Milestone) are automatically hidden from the UI.

## WorkIQ Integration (Meeting Import)

NoteHelper integrates with [WorkIQ](https://github.com/nicklhw/workiq) to import meeting summaries from Microsoft Teams. WorkIQ fetches meeting transcripts and generates structured summaries that can be imported directly into call logs.

### Prerequisites

- **Node.js 18+** — WorkIQ runs via `npx`
- **Microsoft 365 Copilot license** — required for transcript access
- **Delegated authentication** — WorkIQ uses your browser-based Microsoft identity (no service principal needed). You'll be prompted to authenticate in your browser the first time WorkIQ runs.

### How It Works

1. When creating a new call log, click **Import from Meeting** (above the notes editor) or **Auto-fill** (top right)
2. Select the date — NoteHelper queries WorkIQ for your meetings on that date
3. Pick a meeting from the list (NoteHelper auto-selects the best match if a customer is chosen)
4. NoteHelper fetches a ~250-word summary including discussion points, technologies, and action items
5. The summary is inserted into the call log editor

### Customizing the Summary Prompt

The prompt used to generate meeting summaries can be customized:

- **Global default:** Go to **Settings** → **WorkIQ & AI** → edit the **Meeting Summary Prompt** textarea. Use `{title}` and `{date}` as placeholders.
- **Per-meeting override:** When importing a meeting, click **Customize summary prompt** to edit the prompt for just that import.

### No Extra Configuration Needed

WorkIQ uses delegated auth — it authenticates through your browser session. No environment variables are needed beyond having Node.js installed. If `npx` is available on your PATH, WorkIQ will work.

## Scheduled Milestone Sync (Optional)

NoteHelper can automatically sync milestones from MSX on a daily schedule. This keeps your milestone data fresh without manual intervention.

### Setup

Add the `MILESTONE_SYNC_HOUR` environment variable to your `.env` file:

```dotenv
# Sync milestones daily at 3:00 AM
MILESTONE_SYNC_HOUR=3
```

The value is the hour in 24-hour format (0-23) in your **local time zone**. When configured:

- A background thread checks every 60 seconds if it's time to sync
- The sync runs once per day at the configured hour
- All customers with MSX account links are synced
- Results are logged to the console

To disable scheduled sync, remove or comment out the `MILESTONE_SYNC_HOUR` variable.

### Verifying

Check your server logs for messages like:
```
Scheduled milestone sync started (daily at 03:00)
Starting scheduled milestone sync at 2025-01-15T03:00:12
Scheduled sync complete: 42 customers, 5 new, 18 updated
```

### Windows Task Scheduler Alternative

If you prefer to use Windows Task Scheduler instead of the built-in background sync:

1. Create a new Basic Task in Task Scheduler
2. Set the trigger to **Daily** at your preferred time
3. Set the action to run:
   ```
   powershell.exe -Command "Invoke-RestMethod -Method POST -Uri http://localhost:5000/api/milestone-tracker/sync"
   ```
4. Make sure NoteHelper is running when the task fires

## Compliance

This application stores customer account data locally. To remain compliant with organizational data handling policies:

- **Must run on a Microsoft-managed device** (Intune-enrolled or domain-joined)
- **Must reside on a BitLocker-encrypted drive**
- Do not copy the database file (`data/notehelper.db`) to unmanaged devices or unencrypted storage

## License

MIT License - see LICENSE file for details

## Contact

For questions or suggestions, please open an issue on GitHub.
