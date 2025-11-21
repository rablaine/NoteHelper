"""
Entry point for running the NoteHelper Flask application.
Uses the app factory pattern to create and run the app.
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
