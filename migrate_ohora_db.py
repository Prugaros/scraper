import sys
import os
sys.path.append(os.path.abspath('.'))
from common.database import get_db_connection

def migrate():
    """Adds the status column to the ohora_results table."""
    conn = get_db_connection()
    try:
        conn.execute('ALTER TABLE ohora_results ADD COLUMN status TEXT')
        print("Successfully added 'status' column to 'ohora_results' table.")
    except Exception as e:
        if "duplicate column name" in str(e):
            print("'status' column already exists in 'ohora_results' table.")
        else:
            print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
