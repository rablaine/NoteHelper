# NoteHelper

**Version 1.3** - A single-user note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

## Features

### Core Functionality
- Create, edit, and delete call logs with rich text content
- Tag notes with topics (technologies), customers, sellers, and territories
- Search and filter call logs by multiple criteria
- Associate call logs with customer accounts and track relationships
- Track note authors and timestamps with timezone support

### Organizational Structure
- Multi-level organizational hierarchy: PODs → Territories → Sellers → Customers
- Solution Engineers with specialties (Data, Core/Infra, Apps/AI)
- Customer verticals and categories for industry classification
- Seller types (Acquisition vs Growth) with automatic customer type assignment

### User Experience
- **Single-user local deployment** - No authentication required, each instance for one user
- Dark mode with user preferences
- Quick call log creation with customer autocomplete
- **Auto-save drafts** - Call logs automatically save every 10 seconds to prevent data loss
- **Draft management** - View unsaved drafts on home page, restore on return, discard when done
- **Multi-tab coordination** - Draft changes sync across browser tabs in real-time
- Flexible customer list views (alphabetical, grouped by seller, sorted by call count)
- Filter customers by call log activity
- AI-powered topic suggestion using Azure OpenAI
- **WorkIQ meeting import** - Import meeting transcripts and auto-generate call log summaries (requires Node.js)
- Data import/export (JSON and CSV) for backup and migration

### Admin Features
- AI configuration and usage monitoring (optional Azure OpenAI integration)
- Audit logs for AI queries
- Data import/export with CSV and JSON formats
- Analytics dashboard with call trends and insights

## Technology Stack

- **Language:** Python 3.13
- **Framework:** Flask
- **Database:** SQLite (file-based, no server required)
- **UI:** Bootstrap 5
- **ORM:** SQLAlchemy
- **AI Integration:** Azure OpenAI Service / Azure AI Foundry

## Security & Compliance

**Data Protection:**
- ✅ **Encryption at Rest:** SQLite database protected by host disk encryption (BitLocker on Windows, LUKS on Linux)
- ✅ **Access Control:** Single-user deployment - physical access to server required
- ✅ **Audit Trail:** All records include timestamps and user tracking
- ⚠️ **Encryption in Transit:** HTTP only - suitable for trusted internal networks

**For Enhanced Security:**
- Deploy on BitLocker/LUKS encrypted drives
- Access via SSH tunnel when connecting over untrusted networks: `ssh -L 5000:localhost:5000 user@server-ip`
- Use VPN (e.g., Tailscale) for remote access with automatic encryption
- Implement network-level access controls (firewall rules, VLANs)

**Compliance Notes:**
- Designed for internal use on trusted networks
- Regular backups recommended (see Data Management section)
- SSL/TLS can be added via reverse proxy if required by your security policy

## Deployment Options

Choose your preferred deployment method:

### Option 1: Docker (Recommended for Production)

**Prerequisites:**
- Docker and Docker Compose installed

**Quick Start:**

1. Clone the repository:
```bash
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
```

2. Create `.env` file with your secret key:
```bash
cp .env.example .env
# Edit .env and set SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_hex(32))")
```

3. Build and run with Docker Compose:
```bash
docker-compose up -d
```

4. Visit `http://localhost:5000` in your browser

**Using Pre-Built Image from GitHub Container Registry:**

```bash
# Pull the latest image
docker pull ghcr.io/rablaine/notehelper:latest

# Run with docker-compose (recommended - includes volume for data persistence)
docker-compose up -d

# Or run directly (manual volume mounting)
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e SECRET_KEY=your-secret-key-here \
  --name notehelper \
  ghcr.io/rablaine/notehelper:latest
```

**Docker Deployment Features:**
- ✅ **Persistent Data:** SQLite database stored in `./data` volume survives container updates
- ✅ **Automatic Migrations:** Database migrations run automatically on container startup
- ✅ **Easy Updates:** Pull latest image and restart: `docker-compose pull && docker-compose up -d`
- ✅ **Clean Environment:** No Python/pip installation needed on host
- ✅ **Automated Builds:** New images built automatically on every push to `main` branch

**Managing Your Docker Deployment:**

```bash
# View logs
docker-compose logs -f

# Stop the application
docker-compose down

# Update to latest version (manual)
docker-compose pull
docker-compose up -d

# Backup your data
tar -czf notehelper-backup-$(date +%Y%m%d).tar.gz data/

# Restore from backup
tar -xzf notehelper-backup-20241124.tar.gz
```

**Automatic Updates with Watchtower (Optional):**

If you're running [Watchtower](https://containrrr.dev/watchtower/), NoteHelper will automatically update when new versions are published to the container registry. Watchtower monitors your containers and pulls new images when available.

To set up Watchtower for all your containers:

```bash
docker run -d \
  --name watchtower \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --interval 300 \
  --cleanup
```

This checks for updates every 5 minutes (300 seconds) and automatically removes old images after updating. NoteHelper will seamlessly update with zero configuration needed—migrations run automatically on startup.

### Option 2: Local Development (Python)

**Prerequisites:**
- Python 3.13 or higher
- pip and venv
- Node.js 18+ with npm/npx (required for WorkIQ meeting import feature)

**Setup:**

1. Clone the repository:
```bash
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
```

2. Create virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# or
source venv/bin/activate      # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Generate secret key:
python -c "import secrets; print(secrets.token_hex(32))"
# Add the generated key to .env as SECRET_KEY
```

5. Run the application:
```bash
python run.py
```

6. Visit `http://localhost:5000` in your browser

**Note:** The database will be created automatically in `data/notehelper.db` on first run.

## Development

### Running Tests

```powershell
pytest
pytest --cov=app tests/  # with coverage
```

### Code Style

This project follows PEP 8 guidelines and uses type hints. See `.github/copilot-instructions.md` for full coding standards.

## Version History

- **v1.3 (November 2025):** Converted to single-user local deployment with SQLite database, removed authentication and multi-user features
- **v1.2 (November 2025):** Analytics dashboard with insights and trends, comprehensive UI/UX improvements
- **v1.1 (November 2025):** Auto-save draft feature with localStorage, multi-tab coordination, and draft management
- **v1.0 (November 2025):** Production release with multi-user support, Azure AD authentication, AI-powered topic suggestions, organizational hierarchy (PODs/SEs), and comprehensive import/export capabilities

## Contributing

This project is open source and contributions are welcome! Please ensure:

- All tests pass
- Code follows PEP 8 standards
- No secrets or `.env` file committed
- Use conventional commit messages (`feat:`, `fix:`, `docs:`, etc.)

## License

MIT License - see LICENSE file for details

## Contact

For questions or suggestions, please open an issue on GitHub.
