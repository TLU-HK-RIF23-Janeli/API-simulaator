import sqlite3
import json
import re

DB_NAME = "simulator.db"

def _sanitize_identifier(name):
    """Converts arbitrary text to a safe SQLite identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "items"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned

def _resource_segment_for_path(path):
    """Returns the resource segment represented by the path."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "items"
    if len(parts) >= 2 and parts[-1].isdigit():
        return parts[-2]
    return parts[-1]

def _table_for_path(path):
    resource = _resource_segment_for_path(path)
    return _sanitize_identifier(resource)

def _upsert_cached_payload(cursor, path, data):
    payload = json.dumps(data, ensure_ascii=False)
    cursor.execute(
        """
        INSERT INTO cached_responses (path, payload, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            payload = excluded.payload,
            updated_at = CURRENT_TIMESTAMP
        """,
        (path, payload),
    )

def _extract_records(data, resource_segment=None):
    """
    Returns a list of dict records from common API response shapes.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        preferred_keys = ["items", "data", "results"]
        if resource_segment:
            preferred_keys.append(resource_segment)
            if resource_segment.endswith("s") and len(resource_segment) > 1:
                preferred_keys.append(resource_segment[:-1])

        for key in preferred_keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        # Generic fallback: first list-of-dicts field in the object.
        for value in data.values():
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value

        return [data]

    return []

def _to_sql_value(value):
    """Stores primitives directly and nested values as JSON text."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value

def _ensure_dynamic_table(cursor, table_name):
    cursor.execute(
        f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

def _ensure_columns(cursor, table_name, columns):
    if not columns:
        return

    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing = {row[1] for row in cursor.fetchall()}

    for col in columns:
        if col not in existing:
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT')

def _insert_dynamic_records(cursor, table_name, source_path, records):
    if not records:
        return

    column_names = set()
    processed_records = []

    for record in records:
        processed = {}
        for key, value in record.items():
            col = _sanitize_identifier(str(key))
            processed[col] = _to_sql_value(value)
            column_names.add(col)
        processed_records.append(processed)

    _ensure_columns(cursor, table_name, sorted(column_names))

    # Refresh rows originating from this exact request path.
    cursor.execute(f'DELETE FROM "{table_name}" WHERE source_path = ?', (source_path,))

    ordered_cols = ["source_path"] + sorted(column_names)
    placeholders = ", ".join(["?"] * len(ordered_cols))
    col_sql = ", ".join([f'"{col}"' for col in ordered_cols])

    insert_sql = f'INSERT INTO "{table_name}" ({col_sql}) VALUES ({placeholders})'
    for record in processed_records:
        values = [source_path] + [record.get(col) for col in ordered_cols[1:]]
        cursor.execute(insert_sql, values)

def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None

def _table_columns(cursor, table_name):
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    return [row[1] for row in cursor.fetchall()]

def _decode_maybe_json(value):
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value

def _row_to_dict(column_names, row):
    result = {}
    for idx, col in enumerate(column_names):
        result[col] = _decode_maybe_json(row[idx])
    return result

def _resource_fk_candidates(resource_name):
    """Returns likely FK column names for a parent resource segment."""
    base = _sanitize_identifier(resource_name)
    candidates = {f"{base}_id"}
    if base.endswith("s") and len(base) > 1:
        candidates.add(f"{base[:-1]}_id")
    candidates.add("parent_id")
    return list(candidates)

def _select_rows(cursor, table_name, col_sql, where_clauses, params):
    query = f'SELECT {col_sql} FROM "{table_name}"'
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    cursor.execute(query, params)
    return cursor.fetchall()

def init_db():
    """Initializes a simple cache schema: one JSON payload per path."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Stores the complete AI response for each request path.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cached_responses (
            path TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Optional security layer that can block AI generation for specific paths.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            path TEXT PRIMARY KEY,
            reason TEXT,
            blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Simple cache database initialized.")

def save_structured_resource(path, data):
    """Saves the full payload and also writes structured rows into a dynamic table."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    _upsert_cached_payload(cursor, path, data)

    # Additionally store structured records into a table based on the path root.
    table_name = _table_for_path(path)
    resource_segment = _resource_segment_for_path(path)
    records = _extract_records(data, resource_segment=resource_segment)
    _ensure_dynamic_table(cursor, table_name)
    _insert_dynamic_records(cursor, table_name, path, records)

    # Save short aliases so /comments/3 can reuse /books/2/comments/3 data.
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[-1].isdigit():
        alias_path = f"/{resource_segment}/{parts[-1]}"
        if alias_path != path:
            _upsert_cached_payload(cursor, alias_path, data)
    else:
        for record in records:
            if "id" in record and isinstance(record["id"], (str, int)):
                alias_path = f"/{resource_segment}/{record['id']}"
                _upsert_cached_payload(cursor, alias_path, record)

    conn.commit()
    conn.close()
    print("Resource saved.")

def get_resource_by_path(path):
    """Returns parsed JSON payload for path, or None if missing/invalid."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT payload FROM cached_responses WHERE path = ?", (path,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None

def get_dynamic_resource_by_path(path):
    """
    Reads data from dynamic resource tables.
    - /books -> returns list of rows from table books
    - /books/123 -> returns first row where id='123' (fallback row_id)
    """
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    # Decide target table and optional row identifier from path shape.
    # /books -> table books (list)
    # /books/123 -> table books (single item)
    # /books/123/comments -> table comments (nested list)
    # /books/123/comments/77 -> table comments (nested item)
    item_id = None
    if len(parts) >= 2 and parts[-1].isdigit():
        table_segment_index = len(parts) - 2
        item_id = parts[-1]
        source_prefix = "/" + "/".join(parts[:-1])
    else:
        table_segment_index = len(parts) - 1
        source_prefix = "/" + "/".join(parts)

    table_name = _sanitize_identifier(parts[table_segment_index])

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if not _table_exists(cursor, table_name):
        conn.close()
        return None

    columns = _table_columns(cursor, table_name)
    col_sql = ", ".join([f'"{c}"' for c in columns])

    # Build parent filters from all resource/id pairs preceding the target table.
    parent_pairs = []
    i = 0
    while i + 1 < table_segment_index:
        if parts[i + 1].isdigit():
            parent_pairs.append((parts[i], parts[i + 1]))
            i += 2
        else:
            i += 1

    id_clause = None
    id_params = []
    if item_id is not None:
        if "id" in columns:
            id_clause = '"id" = ?'
            id_params = [item_id]
        elif "row_id" in columns and item_id.isdigit():
            id_clause = '"row_id" = ?'
            id_params = [int(item_id)]
        else:
            conn.close()
            return None

    fk_clauses = []
    fk_params = []
    for resource_name, resource_id in parent_pairs:
        match_col = None
        for candidate in _resource_fk_candidates(resource_name):
            if candidate in columns:
                match_col = candidate
                break
        if match_col:
            fk_clauses.append(f'"{match_col}" = ?')
            fk_params.append(resource_id)

    # Attempt 1: ID + FK filters (most accurate when FK columns exist)
    where_1 = []
    params_1 = []
    if id_clause:
        where_1.append(id_clause)
        params_1.extend(id_params)
    where_1.extend(fk_clauses)
    params_1.extend(fk_params)
    rows = _select_rows(cursor, table_name, col_sql, where_1, params_1)

    # Attempt 2: ID + source path prefix fallback
    if not rows:
        where_2 = []
        params_2 = []
        if id_clause:
            where_2.append(id_clause)
            params_2.extend(id_params)
        if "source_path" in columns:
            where_2.append('"source_path" LIKE ?')
            params_2.append(f"{source_prefix}%")
        rows = _select_rows(cursor, table_name, col_sql, where_2, params_2)

    # Attempt 3: ID-only for item endpoints, otherwise full table scan for list endpoints
    if not rows:
        if id_clause:
            rows = _select_rows(cursor, table_name, col_sql, [id_clause], id_params)
        else:
            rows = _select_rows(cursor, table_name, col_sql, [], [])

    conn.close()

    if not rows:
        return None

    if item_id is not None:
        return _row_to_dict(columns, rows[0])
    return [_row_to_dict(columns, row) for row in rows]

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