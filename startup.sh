#!/bin/bash

echo "Starting NoteHelper deployment..."

# Run database migrations
echo "Running database migrations..."
python -m flask db upgrade

# Check migration status
if [ $? -eq 0 ]; then
    echo "Database migrations completed successfully"
else
    echo "Database migration failed!"
    exit 1
fi

# Start Gunicorn with production settings
echo "Starting Gunicorn server..."
gunicorn --bind=0.0.0.0:8000 \
         --workers=2 \
         --threads=4 \
         --timeout=120 \
         --access-logfile=- \
         --error-logfile=- \
         --log-level=info \
         'app:app'
