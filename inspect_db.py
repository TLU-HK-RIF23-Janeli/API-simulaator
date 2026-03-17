import sqlite3
from database import DB_NAME

def inspect_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print("\n--- 1. CACHED RESPONSES ---")
    cursor.execute("SELECT path, updated_at, substr(payload, 1, 120) || '...' FROM cached_responses")
    for row in cursor.fetchall():
        print(row)

    print("\n--- 2. BLACKLIST ---")
    cursor.execute("SELECT * FROM blacklist")
    for row in cursor.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    inspect_data()