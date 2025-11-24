# NoteHelper

**Version 1.3** - A single-user note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

> 📖 **[Read the Development Story](DEVELOPMENT_STORY.md)** - Learn how this 14,000+ line application was built in 42+ hours using AI-assisted "vibe coding" with GitHub Copilot.

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
- Data import/export (JSON and CSV) for backup and migration

### Admin Features
- Domain whitelisting for external accounts
- User management and admin role assignment
- AI configuration and usage monitoring
- Audit logs for AI queries

## Technology Stack

- **Language:** Python 3.13
- **Framework:** Flask
- **Database:** SQLite (file-based, no server required)
- **UI:** Bootstrap 5
- **ORM:** SQLAlchemy
- **AI Integration:** Azure OpenAI Service / Azure AI Foundry

## Prerequisites

- Python 3.13 or higher
- pip and venv

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/rablaine/NoteHelper.git
cd NoteHelper
```

### 2. Create Virtual Environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

```powershell
cp .env.example .env
```

Generate a secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Update `SECRET_KEY` in `.env` with the generated value. The database will be created automatically in `data/notehelper.db` when you first run the application.

### 5. Run the Application

```powershell
python run.py
```

Visit `http://localhost:5000` in your browser.

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
