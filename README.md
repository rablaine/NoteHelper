# NoteHelper

**Version 1.0** - A note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

> 📖 **[Read the Development Story](DEVELOPMENT_STORY.md)** - Learn how this 13,000+ line application was built in 40 hours using AI-assisted "vibe coding" with GitHub Copilot.

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
- Multi-user support with Azure AD authentication and isolated workspaces
- Account linking for Microsoft and external email addresses
- Dark mode with user preferences
- Quick call log creation with customer autocomplete
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
- **Database:** PostgreSQL
- **UI:** Bootstrap 5
- **ORM:** SQLAlchemy
- **Authentication:** Microsoft Entra ID (Azure AD) OAuth 2.0
- **AI Integration:** Azure OpenAI Service / Azure AI Foundry

## Prerequisites

- Python 3.13 or higher
- PostgreSQL 15 or higher
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

Edit `.env` with your database credentials and generate a secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Create PostgreSQL Database

```sql
CREATE DATABASE notehelper;
```

### 6. Initialize Database

```powershell
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

### 7. Run the Application

```powershell
python application.py
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
