import sqlite3
import os
from .config import DATABASE_PATH

def get_db_connection():
    """Create a database connection."""
    # Get the absolute path to the project's root directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, DATABASE_PATH)
    
    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_tables():
    """Initialize all the necessary tables in the database."""
    conn = get_db_connection()
    with conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS ebay_results (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            shipping TEXT,
            list_date TEXT,
            subtitles TEXT,
            condition TEXT,
            photo TEXT,
            failed_parse INTEGER DEFAULT 0
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS poshmark_results (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            photo TEXT,
            failed_parse INTEGER DEFAULT 0
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS disney_results (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            status TEXT,
            photo TEXT
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS OhoraJP_results (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            status TEXT,
            photo TEXT
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS ohora_results (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            status TEXT,
            photo TEXT
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS mercari_results
                 (url text PRIMARY KEY, title text, price text, image text)''')
    conn.close()

def get_all_listing_urls(table_name):
    """Get a list of all the listing URLs in the specified table."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"SELECT url FROM {table_name}")
    urls = [row[0] for row in c.fetchall()]
    conn.close()
    return urls

def increment_failed_parse(table_name, url):
    """Increment the failed_parse value for a given URL in the specified table."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE {table_name} SET failed_parse = failed_parse + 1 WHERE url=?", (url,))
    conn.commit()
    conn.close()

def remove_failed_listings(table_name):
    """Remove listings from the specified table where failed_parse is 10 or more."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"DELETE FROM {table_name} WHERE failed_parse >= 10")
    conn.commit()
    conn.close()

def reset_failed_parse(conn, table_name, url):
    """Reset the failed_parse value for a given URL in the specified table."""
    c = conn.cursor()
    c.execute(f"UPDATE {table_name} SET failed_parse = 0 WHERE url=?", (url,))
    conn.commit()

if __name__ == '__main__':
    initialize_tables()
    print("Database tables initialized.")
