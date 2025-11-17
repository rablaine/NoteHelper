# NoteHelper

A note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

## Features

- Create, edit, and delete notes from customer calls
- Tag notes with technologies, customers, and sellers
- Search and filter notes by multiple criteria
- Associate notes with customer accounts
- Track note authors and timestamps
- User authentication and session management

## Technology Stack

- **Language:** Python 3.13
- **Framework:** Flask
- **Database:** PostgreSQL
- **UI:** Bootstrap 5
- **ORM:** SQLAlchemy
- **Authentication:** Flask-Login

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
python app.py
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

## Project Phases

- **Phase 1 (Current):** Single-file Flask app with Flask-Login authentication
- **Phase 2 (Future):** Refactor to blueprints for better organization
- **Phase 3 (Optional):** Add Azure AD OAuth authentication

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
