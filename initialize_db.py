# initialize_db.py
import sqlite3
import os
import sys

# Add the current directory to the Python path to ensure imports work
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import database
from app import app # Import your Flask app instance

def run_db_setup():
    print("Starting database initialization...")
    conn = None
    try:
        # Determine the database file path from environment variable or default to persistent disk path
        db_path = os.environ.get('DATABASE_PATH', '/var/data/inventory.db') 
        # Ensure the directory for the database file exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Get connection using your database.py function
        conn = database.get_db_connection() 
        # Call your init_db function from database.py
        database.init_db(conn) 
        print("Database initialization complete.")
    except Exception as e:
        print(f"Error during database initialization: {e}")
        sys.exit(1) # Exit with an error code if setup fails
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    with app.app_context(): # Essential for Flask context-dependent functions
        run_db_setup()