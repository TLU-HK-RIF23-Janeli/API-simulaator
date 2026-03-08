import sqlite3
from database import DB_NAME

def inspect_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print("\n--- 1. RESOURCES TABLE ---")
    cursor.execute("SELECT * FROM resources")
    for row in cursor.fetchall():
        print(row)

    print("\n--- 2. PATHS MAPPING ---")
    cursor.execute("SELECT * FROM paths")
    for row in cursor.fetchall():
        print(row)

    print("\n--- 3. ATTRIBUTES (EAV) - TOP 10 ROWS ---")
    cursor.execute("SELECT resource_id, parent_path, value FROM attributes LIMIT 10")
    for row in cursor.fetchall():
        print(f"ID: {row[0]} | Path: {row[1]:<20} | Value: {row[2]}")

    print("\n--- 4. BLACKLIST ---")
    cursor.execute("SELECT * FROM blacklist")
    for row in cursor.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    inspect_data()