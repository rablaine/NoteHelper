#!/bin/bash

echo "=========================================="
echo "Starting NoteHelper deployment..."
echo "=========================================="

# Print Python version
echo "Python version:"
python --version

# Print current directory and contents
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

# Check if run.py exists
if [ -f "run.py" ]; then
    echo "Found run.py in root directory"
else
    echo "ERROR: run.py not found!"
    exit 1
fi

# Set FLASK_APP environment variable
export FLASK_APP=run.py

# Add current directory to Python path to ensure proper imports
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Test database connection
echo "Testing database connection..."
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); print('Database connection successful!')" || {
    echo "ERROR: Database connection failed!"
    echo "Check DATABASE_URL environment variable"
    exit 1
}

# Create any missing tables (safe - only creates tables that don't exist)
echo "Ensuring database tables exist..."
python -c "from app import create_app; from app.models import db; app = create_app(); app.app_context().push(); db.create_all(); print('Database tables verified!')" || {
    echo "ERROR: Database table creation failed!"
    exit 1
}

echo "Database setup completed successfully"

# Start Gunicorn with production settings
echo "Starting Gunicorn server on port 8000..."
gunicorn --bind=0.0.0.0:8000 \
         --workers=2 \
         --threads=4 \
         --timeout=120 \
         --access-logfile=- \
         --error-logfile=- \
         --log-level=info \
         --preload \
         run:app
