import sqlite3
import os
import json
import urllib.parse

DB_NAME = "simulator.db"

def init_db():
    """Initializes the structured EAV database schema."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Main resource table (The Entity)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_type TEXT,
            external_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. Attributes table (The Data Points)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attributes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER,
            key TEXT,
            value TEXT,
            parent_path TEXT, -- Stores the full JSON path like 'specs.engine'
            FOREIGN KEY(resource_id) REFERENCES resources(id) ON DELETE CASCADE
        )
    ''')

    # 3. Path mapping
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paths (
            path TEXT PRIMARY KEY,
            resource_id INTEGER,
            FOREIGN KEY(resource_id) REFERENCES resources(id) ON DELETE CASCADE
        )
    ''')

    # 4. Blacklist table (The Security Layer)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            path TEXT PRIMARY KEY,
            reason TEXT,
            blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Structured database initialized.")

def save_structured_resource(path, data):
    import sqlite3
    import urllib.parse
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    parts = [p for p in path.split('/') if p]
    base_type = parts[0] if parts else "item"

    def flatten_only(obj, res_id, current_json_path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_path = f"{current_json_path}.{k}" if current_json_path else k
                flatten_only(v, res_id, new_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                new_path = f"{current_json_path}[{i}]"
                flatten_only(item, res_id, new_path)
        else:
            cursor.execute(
                "INSERT INTO attributes (resource_id, key, value, parent_path) VALUES (?, ?, ?, ?)",
                (res_id, current_json_path.split('.')[-1], str(obj), current_json_path)
            )

    def scan_for_entities(obj, current_path="", parent_type=None, current_url_prefix=""):
        if isinstance(obj, dict):
            discovery_path = None
            links = obj.get('links') or obj.get('_links')
            if isinstance(links, dict) and 'self' in links:
                discovery_path = links['self']
                if discovery_path and isinstance(discovery_path, str) and discovery_path.startswith('http'):
                    discovery_path = urllib.parse.urlparse(discovery_path).path

            if 'id' in obj:
                entity_id = str(obj['id'])
                entity_type = parent_type if parent_type else base_type
                
                # Alati garanteerime ID-põhise tee (see on kõige kindlam)
                short_path = f"/{entity_type}/{entity_id}"
                
                # Kui meil on prefix (oleme sügaval), ehitame pika tee
                # Nt: /posts/101 + /comments + /501
                if current_url_prefix:
                    predicted_path = f"{current_url_prefix.rstrip('/')}/{entity_type}/{entity_id}"
                else:
                    predicted_path = short_path

                # Loome ressursi
                cursor.execute("INSERT INTO resources (resource_type) VALUES (?)", (entity_type,))
                new_id = cursor.lastrowid
                
                # SALVESTAME KÕIK VARIANDID: 
                # 1. /posts/101 (short_path)
                # 2. /posts/101 (predicted_path - võib olla sama mis short)
                # 3. /posts/slug-nimi (discovery_path - AI poolt antud)
                paths_to_register = {short_path, predicted_path, discovery_path}
                for p in paths_to_register:
                    if p:
                        cursor.execute("INSERT OR IGNORE INTO paths (path, resource_id) VALUES (?, ?)", (p, new_id))
                
                flatten_only(obj, new_id)
                
                # Edasistele lastele anname kaasa ID-põhise prefixi!
                # Nii on kindel, et kommentaarid saavad prefixiks /posts/101, mitte /posts/slug
                new_prefix = short_path
            else:
                new_prefix = current_url_prefix

            for k, v in obj.items():
                next_type = k if k not in ['data', 'items', 'comments_preview'] else parent_type
                scan_for_entities(v, f"{current_path}.{k}", next_type, new_prefix)
        
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                scan_for_entities(item, f"{current_path}[{i}]", parent_type, current_url_prefix)

    # Põhiressursi salvestamine
    cursor.execute("INSERT INTO resources (resource_type) VALUES (?)", ("main",))
    main_id = cursor.lastrowid
    cursor.execute("INSERT OR IGNORE INTO paths (path, resource_id) VALUES (?, ?)", (path, main_id))
    flatten_only(data, main_id)

    # Skaneerime sisu
    scan_for_entities(data, parent_type=base_type)
    

    # --- PÕHIPROTSESS ---
    # Salvestame algse päringu vastuse (nt /posts)
    cursor.execute("DELETE FROM paths WHERE path = ?", (path,))
    cursor.execute("INSERT INTO resources (resource_type) VALUES (?)", ("main",))
    main_id = cursor.lastrowid
    cursor.execute("INSERT INTO paths (path, resource_id) VALUES (?, ?)", (path, main_id))
    
    flatten_only(data, main_id)
    scan_for_entities(data, parent_type=base_type)

    conn.commit()
    conn.close()
    print("Structured resource saved.")

def get_resource_by_path(path):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. ETAPP: Leiame ID (Paths tabel on ainult viit)
    # Kasutame LIKE, et kui andmebaasis on "/comments/1001", 
    # siis ta leiaks selle üles ka "/posts/101/comments/1001" alt.
    cursor.execute("SELECT resource_id FROM paths WHERE path = ? OR path LIKE ?", (path, f"%{path}"))
    res_row = cursor.fetchone()
    
    if not res_row:
        conn.close()
        return None
    
    res_id = res_row[0]

    # 2. ETAPP: Sinu vana kood hakkab tööle!
    # Me ei küsi enam tee järgi, vaid ID järgi. Nii on lollikindel.
    cursor.execute("SELECT parent_path, value FROM attributes WHERE resource_id = ?", (res_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    # --- SIIT ALGAB SINU ORIGINAALNE KOOD ---
    result = {}
    for full_path, value in rows:
        # Normalize paths like 'data[0].id' to 'data.0.id'
        parts = full_path.replace('[', '.').replace(']', '').split('.')
        current = result
        
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            
            if part.isdigit():
                idx = int(part)
                while len(current) <= idx:
                    current.append(None)
                
                if is_last:
                    current[idx] = value
                else:
                    if current[idx] is None:
                        next_part = parts[i+1]
                        current[idx] = [] if next_part.isdigit() else {}
                    current = current[idx]
            else:
                if is_last:
                    current[part] = value
                else:
                    if part not in current or current[part] is None:
                        next_part = parts[i+1]
                        current[part] = [] if next_part.isdigit() else {}
                    current = current[part]
                
    return result

def is_blacklisted(path):
    """
    Checks if a specific path is present in the blacklist table.
    Returns True if blocked, False otherwise.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # We check the 'blacklist' table which we defined in init_db()
    cursor.execute("SELECT 1 FROM blacklist WHERE path = ?", (path,))
    result = cursor.fetchone()
    
    conn.close()
    return result is not None

def add_to_blacklist(path, reason="No reason provided"):
    """
    Manually add a path to the blacklist to prevent AI generation.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO blacklist (path, reason) VALUES (?, ?)", 
                       (path, reason))
        conn.commit()
        print(f"Path {path} has been blacklisted.")
    except Exception as e:
        print(f"Error blacklisting path: {e}")
    finally:
        conn.close()