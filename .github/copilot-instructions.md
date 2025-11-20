# Copilot Instructions

## Project Overview

**Project Name:** NoteHelper

**Description:** A note-taking application for Azure technical sellers to capture and retrieve customer call notes. Enables searching and filtering notes by customer, seller, technologies discussed, and other criteria.

**Target Users:** Azure technical sellers and their teammates

## Technology Stack

**Language(s):** Python 3.13

**Framework(s):** Flask

**Database:** PostgreSQL

**Key Libraries/Packages:**
- Flask - Web framework
- Bootstrap 5 - UI components and styling
- SQLAlchemy - Database ORM
- Flask-Migrate - Database migrations
- psycopg2 - PostgreSQL adapter
- Flask-Login - User session management
- python-dotenv - Environment variable management
- pytest - Testing framework

**Build/Package Tools:** pip, venv

## Project Structure

**Phase 1 (Current): Single-File Structure**
```
/
├── app.py              - Main Flask application (routes, models, logic)
├── templates/          - Jinja2 HTML templates
├── static/             - CSS, JS, images
│   ├── css/
│   └── js/
├── tests/              - pytest test files
├── .env                - Environment variables (not committed)
├── requirements.txt    - Python dependencies
└── migrations/         - Database migration files
```

**Phase 2 (Future): Blueprint Structure**
```
/app
├── __init__.py         - Flask app factory
├── models.py           - Database models
├── routes/
│   ├── customers.py    - Customer blueprint
│   ├── notes.py        - Notes blueprint
│   └── search.py       - Search blueprint
├── auth/
│   ├── flask_login.py  - Username/password auth
│   └── azure_oauth.py  - Azure AD OAuth (optional)
├── templates/
└── static/
/tests
```

## Coding Standards & Best Practices

### Code Style
- Follow PEP 8 style guide for Python code
- Use type hints for function parameters and return values
- Use 4 spaces for indentation
- Maximum line length: 100 characters
- Use docstrings for all functions, classes, and modules

### Naming Conventions
- **Files:** snake_case (e.g., `customer_routes.py`, `note_model.py`)
- **Variables:** snake_case (e.g., `customer_name`, `note_content`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `DATABASE_URL`, `MAX_NOTE_LENGTH`)
- **Functions:** snake_case with verb prefixes (e.g., `get_customer`, `create_note`, `search_by_tag`)
- **Classes:** PascalCase (e.g., `Customer`, `Note`, `User`)
- **Database tables:** snake_case plural (e.g., `customers`, `notes`, `tags`)

### Code Organization
- Start with single-file app.py, refactor to blueprints when file exceeds ~300 lines
- Keep database models in separate section or file
- Group related routes together with clear comments
- Keep functions focused and under 50 lines when possible
- Extract magic numbers and strings into constants at top of file
- Separate business logic from route handlers when complexity grows

### Error Handling
- Use try-except blocks for database operations
- Log errors with context (use Python logging module)
- Return user-friendly error messages in templates
- Handle database constraint violations gracefully
- Use Flask error handlers for 404, 500, etc.

### Testing
- Use pytest for all tests
- **Write tests as you implement features** - Don't wait until later
- Write unit tests for business logic and database operations
- Use Flask test client for route testing
- Tests use isolated SQLite database (configured in `tests/conftest.py`)
- Never run tests against production PostgreSQL database
- Aim for 70%+ code coverage
- Test file naming: `test_*.py` or `*_test.py`
- **Run tests before committing** - Ensure all tests pass with `pytest tests/`
- Add tests for any bugs discovered to prevent regression

## Architecture Patterns

**Design Pattern(s):** MVC (Model-View-Controller) pattern with Flask
- Models: SQLAlchemy ORM classes
- Views: Jinja2 templates
- Controllers: Flask route handlers

**State Management:** Server-side sessions with Flask-Login

**API Design:** Server-rendered templates with Jinja2 (not REST API)
- Use POST for data modifications
- Use GET for queries and searches
- CSRF protection enabled

## Dependencies & Environment

**Required Environment Variables:**
```
DATABASE_URL=postgresql://username:password@localhost:5432/notehelper
SECRET_KEY=your-secret-key-here
FLASK_ENV=development
FLASK_DEBUG=True
```

**Prerequisites:**
- Python 3.13+
- PostgreSQL 15+
- pip and venv

## Development Workflow

**Setup:**
```powershell
# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your database credentials

# Initialize database
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

**Running Locally:**
```powershell
.\venv\Scripts\Activate.ps1
python app.py
# or
flask run
```

**Testing:**
```powershell
pytest
pytest --cov=app tests/  # with coverage
```

## Documentation Standards

- Use docstrings for all functions, classes, and modules (Google style preferred)
- Document complex database queries with inline comments
- Keep README.md updated with setup instructions and features
- Document environment variables in .env.example
- Add comments explaining business logic, not obvious code

## Security Considerations

- Never commit .env file or secrets to Git
- Use SQLAlchemy ORM to prevent SQL injection (no raw SQL)
- Enable CSRF protection on all forms
- Hash passwords with werkzeug.security (never store plain text)
- Sanitize user input before displaying in templates
- Use Flask-Login's login_required decorator for protected routes

## Performance Guidelines

- Add database indexes on frequently queried columns (customer_id, tags, created_at)
- Use pagination for large result sets
- Eager load relationships to avoid N+1 queries
- Minimize Bootstrap JavaScript usage (only include what's needed)
- Use Flask caching for expensive queries if needed

## Git & Version Control

**Branching Strategy:** Simple feature branches (main is stable)
- Create feature branches from main
- Merge back to main when complete

**Commit Message Format:** Conventional Commits
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions or changes

**Commit Workflow:**
1. Write code and corresponding tests together
2. Run `pytest tests/` to verify all tests pass
3. Stage changes with `git add`
4. Commit with descriptive message
5. Push to remote when ready

**Pull Request Requirements:**
- All tests must pass (`pytest tests/`)
- Code follows PEP 8 standards
- No secrets or .env file committed
- Tests included for new features or bug fixes

## UI/UX Conventions

**Visual Styling:**
- **Sellers:** Always display as badge tags with `bg-primary` styling and person icon (`<i class="bi bi-person"></i>`), unless used in page headers/titles
  - Example: `<a href="{{ url_for('seller_view', id=seller.id) }}" class="badge bg-primary text-decoration-none"><i class="bi bi-person"></i> {{ seller.name }}</a>`
- **Territories:** Always display as badge tags with `bg-info text-dark` styling and location icon (`<i class="bi bi-geo-alt"></i>`), unless used in page headers/titles
  - Example: `<a href="{{ url_for('territory_view', id=territory.id) }}" class="badge bg-info text-dark text-decoration-none"><i class="bi bi-geo-alt"></i> {{ territory.name }}</a>`
- **Topics:** Display as badge tags with `bg-warning text-dark` styling and tag icon (`<i class="bi bi-tag"></i>`)
- Maintain consistent badge styling across all views for visual parity

## Communication Style

**Tone & Personality:**
- Be chill and conversational, like you're pair programming with a friend
- Embrace a neurodivergent coding style - hyperfocus on details when they matter, but don't overthink the simple stuff
- Modern slang is fine when it flows naturally, but never force it - if it feels like you're trying too hard, just speak normally
- Appreciate good code the way gamers appreciate a clean speedrun - efficiency is satisfying
- When explaining things, keep it real and straightforward - no corporate speak or needless formality
- If something is genuinely fire or straight up broken, just say it
- Channel that "it's 2am and the code finally works" energy when celebrating successful changes, but only when it's actually earned
- The personality should be subtle background flavor, not the main character - focus on being helpful first, personality second

## Additional Notes

**Development Phases:**
- **Phase 1 (Current):** Single-file app with Flask-Login authentication
- **Phase 2 (Future):** Refactor to blueprints when complexity grows
- **Phase 3 (Optional):** Add Azure AD OAuth as additional login method

**Key Features:**
- Create/edit/delete notes (call logs)
- Tag notes with technologies, customers, sellers, territories
- Search and filter notes by multiple criteria
- Associate notes with customer accounts
- Track who created each note and when
- Data import/export for backup and migration (JSON and CSV formats)
- User preferences (dark mode, view options)
- Clickable UI elements throughout for improved navigation

**Open Source:**
- This project is open source and intended to be easy for others to contribute to
- Write clear, self-documenting code
- Prioritize simplicity and maintainability over clever solutions

---

**Last Updated:** November 19, 2025
