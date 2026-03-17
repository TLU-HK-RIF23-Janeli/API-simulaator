import sqlite3
import os
from database import DB_NAME

def clear_database():
    """Deletes the database file to ensure a completely fresh start."""
    if os.path.exists(DB_NAME):
        try:
            os.remove(DB_NAME)
            print(f"Successfully deleted {DB_NAME}.")
        except Exception as e:
            print(f"Error deleting database file: {e}")
    else:
        print("Database file does not exist. Nothing to delete.")
