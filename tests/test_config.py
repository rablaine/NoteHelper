# Test configuration - overrides database URI for testing
import tempfile
import os

# Create temporary test database
TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix='.db')

# Test configuration
SQLALCHEMY_DATABASE_URI = f'sqlite:///{TEST_DB_PATH}'
TESTING = True
WTF_CSRF_ENABLED = False
SQLALCHEMY_TRACK_MODIFICATIONS = False
