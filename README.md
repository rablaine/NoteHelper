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

3. **Import accounts:** In the app, go to **Admin Panel** → **Import My Accounts**. This pulls in your customer accounts.

4. **Import milestones:** From the Admin Panel, run **Import Milestones** to pull in your milestone data.

5. **Import revenue history:** Go to **Revenue Analyzer** and import revenue data for your accounts.

Once these steps are complete, you're all set — your customer accounts, milestones, and revenue history are loaded and ready to go.

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
