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


def _data_columns_for_table(cursor, table_name):
    system_columns = {"row_id", "source_path", "created_at"}
    return [col for col in _table_columns(cursor, table_name) if col not in system_columns]


def get_existing_schema_for_path(path):
    """
    Returns existing data columns for the resource table inferred from path.
    Empty list means schema not established yet.
    """
    table_name = _table_for_path(path)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        if not _table_exists(cursor, table_name):
            return []
        return _data_columns_for_table(cursor, table_name)
    finally:
        conn.close()


def validate_payload_against_existing_schema(path, data, allow_missing_id=False):
    """
    Validates payload record fields against existing table schema for path.
    If schema is not established, validation passes.
    
    Checks:
    1. No unknown columns (not in schema)
    2. All schema columns present (except system columns: row_id, source_path, created_at, and optionally id)
    
    Args:
        allow_missing_id: If True, id is not required (for user POST operations where id is auto-generated)
    """
    schema_columns = set(get_existing_schema_for_path(path))
    if not schema_columns:
        return True, None

    # System columns don't need to be provided by user
    system_columns = {"row_id", "source_path", "created_at"}
    if allow_missing_id:
        system_columns.add("id")
    required_columns = schema_columns - system_columns

    resource_segment = _resource_segment_for_path(path)
    records = _extract_records(data, resource_segment=resource_segment)
    if not records:
        return True, None

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        record_columns = {_sanitize_identifier(str(key)) for key in record.keys()}
        
        # Check for unknown columns
        unknown_columns = sorted(record_columns - schema_columns)
        if unknown_columns:
            return False, {
                "path": path,
                "schema_columns": sorted(schema_columns),
                "unknown_columns": unknown_columns,
                "record_index": idx,
            }
        
        # Check for missing required columns
        missing_columns = sorted(required_columns - record_columns)
        if missing_columns:
            return False, {
                "path": path,
                "schema_columns": sorted(schema_columns),
                "missing_columns": missing_columns,
                "required_columns": sorted(required_columns),
                "record_index": idx,
            }

    return True, None

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

def _preferred_fk_field(resource_name):
    """Returns a stable FK field name for a parent resource segment."""
    base = _sanitize_identifier(resource_name)
    if base.endswith("s") and len(base) > 1:
        base = base[:-1]
    return f"{base}_id"

def _parent_pairs_for_path(path):
    """Returns parent resource/id pairs that scope the current path."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return []

    if len(parts) >= 2 and parts[-1].isdigit():
        table_segment_index = len(parts) - 2
    else:
        table_segment_index = len(parts) - 1

    parent_pairs = []
    index = 0
    while index + 1 < table_segment_index:
        if parts[index + 1].isdigit():
            parent_pairs.append((parts[index], parts[index + 1]))
            index += 2
        else:
            index += 1

    return parent_pairs


def _blacklisted_numeric_ids(cursor, table_name):
    """Returns numeric IDs that are blacklisted for a given resource table."""
    if not _table_exists(cursor, "blacklist"):
        return set()

    cursor.execute('SELECT "path" FROM "blacklist"')
    blocked_ids = set()
    for row in cursor.fetchall():
        path = row[0]
        if not isinstance(path, str):
            continue

        parts = [p for p in path.split("/") if p]
        if len(parts) < 2 or not parts[-1].isdigit():
            continue

        resource_segment = _resource_segment_for_path(path)
        if _sanitize_identifier(resource_segment) != table_name:
            continue

        try:
            blocked_ids.add(int(parts[-1]))
        except ValueError:
            continue

    return blocked_ids

def _existing_numeric_ids(cursor, table_name, exclude_source_path=None):
    """Returns integer IDs already used in a dynamic table."""
    if not _table_exists(cursor, table_name):
        return set()

    columns = _table_columns(cursor, table_name)
    if "id" not in columns:
        return set()

    query = f'SELECT "id" FROM "{table_name}"'
    params = []
    if exclude_source_path and "source_path" in columns:
        query += ' WHERE "source_path" != ?'
        params.append(exclude_source_path)

    cursor.execute(query, params)
    existing_ids = set()
    for row in cursor.fetchall():
        value = row[0]
        try:
            existing_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    # Never reuse IDs that are explicitly blacklisted/deleted.
    existing_ids.update(_blacklisted_numeric_ids(cursor, table_name))

    return existing_ids

def _normalize_generated_data(cursor, path, data):
    """
    Normalizes generated records so IDs stay unique per resource table and
    nested resources keep a consistent parent foreign key.
    """
    resource_segment = _resource_segment_for_path(path)
    records = _extract_records(data, resource_segment=resource_segment)
    if not records:
        return data

    table_name = _table_for_path(path)
    existing_ids = _existing_numeric_ids(cursor, table_name, exclude_source_path=path)
    next_id = max(existing_ids, default=0) + 1
    parent_pairs = _parent_pairs_for_path(path)
    parts = [p for p in path.split("/") if p]
    path_item_id = int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else None

    for record in records:
        if not isinstance(record, dict):
            continue

        for parent_resource, parent_id in parent_pairs:
            fk_field = _preferred_fk_field(parent_resource)
            record[fk_field] = int(parent_id)

        if path_item_id is not None:
            record["id"] = path_item_id
            existing_ids.add(path_item_id)
            next_id = max(next_id, path_item_id + 1)
            continue

        while next_id in existing_ids:
            next_id += 1
        record["id"] = next_id
        existing_ids.add(next_id)
        next_id += 1

    return data

def _select_rows(cursor, table_name, col_sql, where_clauses, params):
    query = f'SELECT {col_sql} FROM "{table_name}"'
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    cursor.execute(query, params)
    return cursor.fetchall()

def _find_dynamic_row_for_item_path(cursor, path):
    """
    Returns the first matching dynamic-table row for an item path, including
    row metadata needed for scoped updates.
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not parts[-1].isdigit():
        return None, None, None

    table_segment_index = len(parts) - 2
    item_id = parts[-1]
    source_prefix = "/" + "/".join(parts[:-1])
    table_name = _sanitize_identifier(parts[table_segment_index])

    if not _table_exists(cursor, table_name):
        return None, None, None

    columns = _table_columns(cursor, table_name)
    col_sql = ", ".join([f'"{column}"' for column in columns])

    id_clause = None
    id_params = []
    if "id" in columns:
        id_clause = '"id" = ?'
        id_params = [item_id]
    elif "row_id" in columns and item_id.isdigit():
        id_clause = '"row_id" = ?'
        id_params = [int(item_id)]
    else:
        return None, None, None

    parent_pairs = _parent_pairs_for_path(path)
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

    has_parent_scope = len(parent_pairs) > 0

    where_1 = [id_clause]
    params_1 = list(id_params)
    where_1.extend(fk_clauses)
    params_1.extend(fk_params)
    rows = _select_rows(cursor, table_name, col_sql, where_1, params_1)

    if not rows and "source_path" in columns:
        where_2 = [id_clause, '"source_path" LIKE ?']
        params_2 = list(id_params) + [f"{source_prefix}%"]
        rows = _select_rows(cursor, table_name, col_sql, where_2, params_2)

    if not rows and not has_parent_scope:
        rows = _select_rows(cursor, table_name, col_sql, [id_clause], id_params)

    if not rows:
        return None, None, None

    return table_name, columns, _row_to_dict(columns, rows[0])

def _item_paths_for_dynamic_row(path, row):
    """Collects item cache paths that should stay in sync for a single row."""
    item_paths = {path}

    item_id = row.get("id")
    if item_id is None:
        return item_paths

    resource_segment = _resource_segment_for_path(path)
    alias_path = f"/{resource_segment}/{item_id}"
    item_paths.add(alias_path)

    source_path = row.get("source_path")
    if isinstance(source_path, str) and source_path:
        source_parts = [part for part in source_path.split("/") if part]
        if source_parts:
            if source_parts[-1].isdigit():
                item_paths.add(source_path)
            else:
                item_paths.add(f"{source_path}/{item_id}")

    return {candidate for candidate in item_paths if isinstance(candidate, str) and candidate}

def _collection_paths_for_dynamic_row(path, row):
    """Collects collection cache paths affected by an item update."""
    collection_paths = set()

    request_collection_path = _collection_path_for_item(path)
    if request_collection_path:
        collection_paths.add(request_collection_path)

    for item_path in _item_paths_for_dynamic_row(path, row):
        collection_path = _collection_path_for_item(item_path)
        if collection_path:
            collection_paths.add(collection_path)

    source_path = row.get("source_path")
    if isinstance(source_path, str) and source_path:
        source_parts = [part for part in source_path.split("/") if part]
        if source_parts:
            if source_parts[-1].isdigit():
                source_collection_path = _collection_path_for_item(source_path)
            else:
                source_collection_path = source_path
            if source_collection_path:
                collection_paths.add(source_collection_path)

    return collection_paths

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

def save_user_resource(path, data):
    """
    Saves a user-submitted resource (POST) to a collection.
    Unlike save_structured_resource (for AI), this APPENDS a new item instead of replacing.
    Auto-generates ID if not present, respects existing schema.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # For user POST, ensure data is dict (single item), not a list
    if isinstance(data, list):
        data = data[0] if data else {}
    
    if not isinstance(data, dict):
        conn.close()
        return {"error": "Invalid data type"}

    # Auto-generate ID if not provided
    table_name = _table_for_path(path)
    if "id" not in data:
        existing_ids = _existing_numeric_ids(cursor, table_name, exclude_source_path=None)
        next_id = max(existing_ids, default=0) + 1
        data["id"] = next_id

    # Add parent foreign keys if this is a nested path
    parent_pairs = _parent_pairs_for_path(path)
    for parent_resource, parent_id in parent_pairs:
        fk_field = _preferred_fk_field(parent_resource)
        data[fk_field] = int(parent_id)

    # Ensure table exists and has the necessary columns
    _ensure_dynamic_table(cursor, table_name)
    
    # For POST, we don't delete previous rows like we do for AI refresh
    # Just insert this new item
    resource_segment = _resource_segment_for_path(path)
    records = [data] if isinstance(data, dict) else _extract_records(data, resource_segment=resource_segment)
    
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

    # Insert without deleting previous rows (unlike _insert_dynamic_records)
    ordered_cols = ["source_path"] + sorted(column_names)
    placeholders = ", ".join(["?"] * len(ordered_cols))
    col_sql = ", ".join([f'"{col}"' for col in ordered_cols])

    insert_sql = f'INSERT INTO "{table_name}" ({col_sql}) VALUES ({placeholders})'
    for record in processed_records:
        values = [path] + [record.get(col) for col in ordered_cols[1:]]
        cursor.execute(insert_sql, values)

    # Invalidate collection cache so next GET refreshes
    cursor.execute("DELETE FROM cached_responses WHERE path = ?", (path,))

    # Save alias for short path access (e.g. /comments/5 for /books/1/comments/5)
    if "id" in data:
        alias_path = f"/{resource_segment}/{data['id']}"
        if alias_path != path:
            _upsert_cached_payload(cursor, alias_path, data)

    conn.commit()
    conn.close()
    print("User resource saved.")
    return data

def update_user_resource(path, data):
    """
    Updates an existing single resource in place.
    The payload is expected to be the fully merged public record.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        if isinstance(data, list):
            data = data[0] if data else {}

        if not isinstance(data, dict):
            return {"error": "Invalid data type"}

        table_name, columns, existing_row = _find_dynamic_row_for_item_path(cursor, path)
        if existing_row is None:
            return None

        update_columns = _data_columns_for_table(cursor, table_name)
        processed = {
            _sanitize_identifier(str(key)): _to_sql_value(value)
            for key, value in data.items()
        }

        assignments = []
        values = []
        for column in update_columns:
            if column not in processed:
                continue
            assignments.append(f'"{column}" = ?')
            values.append(processed[column])

        if not assignments:
            return {"error": "No updatable fields"}

        if "source_path" in columns:
            assignments.append('"source_path" = ?')
            values.append(existing_row.get("source_path"))

        values.append(existing_row["row_id"])
        cursor.execute(
            f'UPDATE "{table_name}" SET {", ".join(assignments)} WHERE "row_id" = ?',
            values,
        )

        updated_row = dict(existing_row)
        updated_row.update(data)

        for item_path in _item_paths_for_dynamic_row(path, updated_row):
            _upsert_cached_payload(cursor, item_path, data)

        for collection_path in _collection_paths_for_dynamic_row(path, updated_row):
            cursor.execute("DELETE FROM cached_responses WHERE path = ?", (collection_path,))

        conn.commit()
        return data
    except Exception as e:
        conn.rollback()
        print(f"Error updating resource: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def save_structured_resource(path, data):
    """Saves the full payload and also writes structured rows into a dynamic table."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    data = _normalize_generated_data(cursor, path, data)

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
        # Invalidate parent collection cache so future collection reads include this item.
        collection_path = "/" + "/".join(parts[:-1])
        cursor.execute("DELETE FROM cached_responses WHERE path = ?", (collection_path,))

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
    return data

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

    id_clause = None # goes to SQLite query as a filter for the item ID (e.g. "id = ?")
    id_params = []  # parameters for the ID filter (e.g. [123])
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

    has_parent_scope = len(parent_pairs) > 0

    # Attempt 1: ID + FK filters (most accurate when FK columns exist)
    where_1 = []
    params_1 = []
    if id_clause:
        where_1.append(id_clause)
        params_1.extend(id_params)
    where_1.extend(fk_clauses)
    params_1.extend(fk_params)
    rows = _select_rows(cursor, table_name, col_sql, where_1, params_1) if where_1 else []

    # Attempt 2: ID + source path prefix fallback
    if not rows and "source_path" in columns:
        where_2 = []
        params_2 = []
        if id_clause:
            where_2.append(id_clause)
            params_2.extend(id_params)
        # For nested resources we always scope by parent path prefix.
        if has_parent_scope or id_clause:
            where_2.append('"source_path" LIKE ?')
            params_2.append(f"{source_prefix}%")
        rows = _select_rows(cursor, table_name, col_sql, where_2, params_2)

    # Attempt 3:
    # - For top-level item endpoints, allow ID-only fallback.
    # - For top-level list endpoints, allow full table scan.
    # - For nested endpoints, NEVER do unrestricted scans across all parents.
    if not rows:
        if id_clause:
            if has_parent_scope:
                rows = []
            else:
                rows = _select_rows(cursor, table_name, col_sql, [id_clause], id_params)
        else:
            if has_parent_scope:
                rows = []
            else:
                rows = _select_rows(cursor, table_name, col_sql, [], [])

    conn.close()

    if not rows:
        return None

    if item_id is not None:
        return _row_to_dict(columns, rows[0])
    return [_row_to_dict(columns, row) for row in rows]

def has_conflicting_nested_item(path):
    """
    Returns True when a nested item path refers to an ID that exists in the
    target resource table, but only under a different parent scope.
    Example: /books/2/comments/1 when comment id=1 exists under /books/1.
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4 or not parts[-1].isdigit():
        return False

    table_segment_index = len(parts) - 2
    item_id = parts[-1]
    table_name = _sanitize_identifier(parts[table_segment_index])

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        if not _table_exists(cursor, table_name):
            return False

        columns = _table_columns(cursor, table_name)
        if "id" not in columns:
            return False

        parent_pairs = _parent_pairs_for_path(path)
        if not parent_pairs:
            return False

        cursor.execute(
            f'SELECT 1 FROM "{table_name}" WHERE "id" = ? LIMIT 1',
            (item_id,),
        )
        if cursor.fetchone() is None:
            return False

        fk_clauses = []
        fk_params = []
        for resource_name, resource_id in parent_pairs:
            match_col = None
            for candidate in _resource_fk_candidates(resource_name):
                if candidate in columns:
                    match_col = candidate
                    break
            if match_col is None:
                return False
            fk_clauses.append(f'"{match_col}" = ?')
            fk_params.append(resource_id)

        where = ' AND '.join(['"id" = ?'] + fk_clauses)
        cursor.execute(
            f'SELECT 1 FROM "{table_name}" WHERE {where} LIMIT 1',
            [item_id] + fk_params,
        )
        return cursor.fetchone() is None
    finally:
        conn.close()

def is_blacklisted(path):
    """
    Checks if a specific path is present in the blacklist table.
    Returns True if blocked, False otherwise.

    Also checks the short alias path of an item (e.g. /comments/5 for
    /books/4/comments/5) so that deleting /comments/5 blocks all qualified
    variants of comment 5 regardless of which parent path is used.
    """
    parts = [p for p in path.split("/") if p]

    paths_to_check = [path]

    # For nested item paths like /books/4/comments/5 also check /comments/5.
    if len(parts) >= 4 and parts[-1].isdigit():
        alias = f"/{parts[-2]}/{parts[-1]}"
        if alias != path:
            paths_to_check.append(alias)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        for candidate in paths_to_check:
            cursor.execute(
                """
                SELECT 1
                FROM blacklist
                WHERE path = ? OR ? LIKE path || '/%'
                LIMIT 1
                """,
                (candidate, candidate),
            )
            if cursor.fetchone() is not None:
                return True
        return False
    finally:
        conn.close()

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

def _delete_dynamic_rows_for_path(cursor, path):
    """
    Deletes rows from the dynamic table inferred from path.
    Returns number of deleted rows.
    """
    parts = [p for p in path.split("/") if p]
    if not parts:
        return 0

    item_id = None
    if len(parts) >= 2 and parts[-1].isdigit():
        table_segment_index = len(parts) - 2
        item_id = parts[-1]
    else:
        table_segment_index = len(parts) - 1

    table_name = _sanitize_identifier(parts[table_segment_index])
    if not _table_exists(cursor, table_name):
        return 0

    columns = _table_columns(cursor, table_name)

    if item_id is not None:
        # Prefer deleting by stable resource "id", fallback to SQLite row_id.
        if "id" in columns:
            cursor.execute(f'DELETE FROM "{table_name}" WHERE "id" = ?', (item_id,))
        elif "row_id" in columns and item_id.isdigit():
            cursor.execute(f'DELETE FROM "{table_name}" WHERE "row_id" = ?', (int(item_id),))
        else:
            return 0
    else:
        # Remove rows generated for this collection path (and nested children of it).
        cursor.execute(
            f'DELETE FROM "{table_name}" WHERE source_path = ? OR source_path LIKE ?',
            (path, f"{path}/%"),
        )

    return cursor.rowcount if cursor.rowcount is not None else 0

def _delete_dynamic_rows_for_subtree(cursor, path):
    """
    Deletes rows in all dynamic tables where source_path is under path.
    Returns total number of deleted rows.
    """
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT IN ('cached_responses', 'blacklist', 'sqlite_sequence')
        """
    )
    table_names = [row[0] for row in cursor.fetchall()]

    deleted_total = 0
    for table_name in table_names:
        columns = _table_columns(cursor, table_name)
        if "source_path" not in columns:
            continue

        cursor.execute(
            f'DELETE FROM "{table_name}" WHERE source_path LIKE ?',
            (f"{path}/%",),
        )
        deleted_total += cursor.rowcount if cursor.rowcount is not None else 0

    return deleted_total

def _collect_alias_paths_for_subtree(cursor, path):
    """
    Collects short alias paths (e.g. /comments/1) for dynamic rows stored under path.
    """
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT IN ('cached_responses', 'blacklist', 'sqlite_sequence')
        """
    )
    table_names = [row[0] for row in cursor.fetchall()]

    alias_paths = set()
    for table_name in table_names:
        columns = _table_columns(cursor, table_name)
        if "source_path" not in columns or "id" not in columns:
            continue

        cursor.execute(
            f'SELECT "id" FROM "{table_name}" WHERE source_path = ? OR source_path LIKE ?',
            (path, f"{path}/%"),
        )
        for row in cursor.fetchall():
            item_id = row[0]
            if item_id is None:
                continue
            alias_paths.add(f"/{table_name}/{item_id}")

    return alias_paths

def _collection_path_for_item(path):
    """
    Returns the parent collection path for an item path, or None.
    Example: /books/1 -> /books, /books/1/comments/3 -> /books/1/comments
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not parts[-1].isdigit():
        return None
    return "/" + "/".join(parts[:-1])

def _alias_path_for_item(path):
    """
    Returns the short alias path for an item path, or None.
    Example: /books/1/comments/3 -> /comments/3
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not parts[-1].isdigit():
        return None

    resource_segment = _resource_segment_for_path(path)
    return f"/{resource_segment}/{parts[-1]}"

def _collect_qualified_paths_for_alias(cursor, path):
    """
    For a short alias path like /comments/2, finds all full qualified paths
    (e.g. /books/5/comments/2) by looking up source_path in the dynamic table.
    Only applies to 2-segment item paths (/<resource>/<id>).
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2 or not parts[-1].isdigit():
        return set()

    table_name = _sanitize_identifier(parts[0])
    item_id = parts[1]

    if not _table_exists(cursor, table_name):
        return set()

    columns = _table_columns(cursor, table_name)
    if "id" not in columns or "source_path" not in columns:
        return set()

    cursor.execute(
        f'SELECT source_path FROM "{table_name}" WHERE "id" = ?',
        (item_id,),
    )
    qualified_paths = set()
    for row in cursor.fetchall():
        source_path = row[0]
        if source_path and source_path != path:
            qualified_paths.add(f"{source_path}/{item_id}")

    return qualified_paths


def delete_resource_and_blacklist(path, reason="Deleted by API client"):
    """
    Deletes a resource from cache/dynamic tables and blacklists the path
    so AI generation cannot recreate it.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    deleted_cache_rows = 0
    deleted_dynamic_rows = 0
    try:
        alias_paths = _collect_alias_paths_for_subtree(cursor, path)
        direct_alias_path = _alias_path_for_item(path)
        if direct_alias_path and direct_alias_path != path:
            alias_paths.add(direct_alias_path)

        # If this is a short alias (e.g. /comments/2), also blacklist all full
        # qualified paths for that item (e.g. /books/5/comments/2).
        qualified_paths = _collect_qualified_paths_for_alias(cursor, path)
        alias_paths.update(qualified_paths)

        collection_paths_to_invalidate = set()

        collection_path = _collection_path_for_item(path)
        if collection_path:
            collection_paths_to_invalidate.add(collection_path)

        for alias_path in alias_paths:
            alias_collection_path = _collection_path_for_item(alias_path)
            if alias_collection_path:
                collection_paths_to_invalidate.add(alias_collection_path)

        cursor.execute(
            "DELETE FROM cached_responses WHERE path = ? OR path LIKE ?",
            (path, f"{path}/%"),
        )
        deleted_cache_rows = cursor.rowcount if cursor.rowcount is not None else 0

        for alias_path in alias_paths:
            cursor.execute("DELETE FROM cached_responses WHERE path = ?", (alias_path,))
            deleted_cache_rows += cursor.rowcount if cursor.rowcount is not None else 0

        for collection_path in collection_paths_to_invalidate:
            cursor.execute("DELETE FROM cached_responses WHERE path = ?", (collection_path,))
            deleted_cache_rows += cursor.rowcount if cursor.rowcount is not None else 0

        deleted_dynamic_rows = _delete_dynamic_rows_for_path(cursor, path)
        deleted_dynamic_rows += _delete_dynamic_rows_for_subtree(cursor, path)

        cursor.execute(
            """
            INSERT INTO blacklist (path, reason, blocked_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(path) DO UPDATE SET
                reason = excluded.reason,
                blocked_at = CURRENT_TIMESTAMP
            """,
            (path, reason),
        )

        for alias_path in alias_paths:
            cursor.execute(
                """
                INSERT INTO blacklist (path, reason, blocked_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(path) DO UPDATE SET
                    reason = excluded.reason,
                    blocked_at = CURRENT_TIMESTAMP
                """,
                (alias_path, reason),
            )

        conn.commit()
        return {
            "path": path,
            "deleted_cache_rows": deleted_cache_rows,
            "deleted_dynamic_rows": deleted_dynamic_rows,
            "blacklisted_alias_paths": len(alias_paths),
            "blacklisted": True,
        }
    except Exception as e:
        conn.rollback()
        print(f"Error deleting/blacklisting path: {e}")
        return {
            "path": path,
            "deleted_cache_rows": deleted_cache_rows,
            "deleted_dynamic_rows": deleted_dynamic_rows,
            "blacklisted": False,
            "error": str(e),
        }
    finally:
        conn.close()