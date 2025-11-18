import os
from dotenv import load_dotenv
import psycopg2
from pathlib import Path

# Load environment variables from specific path
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

database_url = os.getenv('DATABASE_URL')
print(f"DATABASE_URL from env: {database_url}")
print(f"Testing connection...")

try:
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    # Test the connection
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✅ Successfully connected to PostgreSQL!")
    print(f"Server version: {version[0][:80]}")
    
    # Check database name
    cursor.execute("SELECT current_database();")
    db_name = cursor.fetchone()
    print(f"Connected to database: {db_name[0]}")
    
    cursor.close()
    conn.close()
    print("✅ Database connection validated!")
    
except Exception as e:
    print(f"❌ Connection failed: {type(e).__name__}")
    print(f"Error: {str(e)}")
