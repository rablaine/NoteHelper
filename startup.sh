#!/bin/bash

echo "=========================================="
echo "Starting NoteHelper deployment..."
echo "=========================================="

# Print Python version
echo "Python version:"
python --version

# Check if app.py exists
if [ -f "app.py" ]; then
    echo "Found app.py in root directory"
else
    echo "ERROR: app.py not found!"
    exit 1
fi

# Set FLASK_APP environment variable
export FLASK_APP=app.py

# Test database connection
echo "Testing database connection..."
python -c "from app import app, db; app.app_context().push(); print('Database connection successful!')" || {
    echo "ERROR: Database connection failed!"
    echo "Check DATABASE_URL environment variable"
    exit 1
}

# Run database migrations
echo "Running database migrations..."
python -m flask db upgrade || {
    echo "ERROR: Database migration failed!"
    exit 1
}

echo "Database migrations completed successfully"

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
         app:app
