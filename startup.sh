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

# Verify app can start (creates tables + runs migrations automatically)
echo "Verifying database and running migrations..."
python -c "from app import create_app; app = create_app(); print('Database ready!')" || {
    echo "ERROR: Database setup failed!"
    echo "Check DATABASE_URL environment variable"
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
