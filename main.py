import time
import re
from flask import Flask, request, jsonify
import database
import ai_client
import reset_db

app = Flask(__name__)
app.json.sort_keys = False  # Preserve the order of JSON keys as they are defined in the database

# On startup, initialize the database
database.init_db()


def _resource_exists(path):
    data = database.get_resource_by_path(path)
    if data is not None:
        return True
    data = database.get_dynamic_resource_by_path(path)
    return data is not None


def _parent_item_path_for_nested_collection(path):
    """
    Returns the immediate parent item path for nested collection endpoints.
    Example: /books/999/comments -> /books/999
    """
    parts = [p for p in path.split('/') if p]
    if len(parts) < 3:
        return None
    if parts[-1].isdigit():
        return None
    if not parts[-2].isdigit():
        return None
    return "/" + "/".join(parts[:-1])

def _find_parent_context(path):
    """Finds the nearest parent path that already exists in cache or dynamic tables."""
    parts = [p for p in path.split('/') if p]
    if len(parts) < 2:
        return None, None

    # Trim from right to left: /a/b/c -> /a/b -> /a
    for i in range(len(parts) - 1, 0, -1):
        candidate = "/" + "/".join(parts[:i])

        data = database.get_resource_by_path(candidate)
        if data is None:
            data = database.get_dynamic_resource_by_path(candidate)

        if data is not None:
            return candidate, data

    return None, None


def _preferred_fk_field(resource_name):
    base = resource_name.strip().lower().replace("-", "_")
    if base.endswith("s") and len(base) > 1:
        base = base[:-1]
    return f"{base}_id"


def _parent_pairs_for_path(path):
    parts = [p for p in path.split('/') if p]
    if len(parts) < 4 or not parts[-1].isdigit():
        return []

    table_segment_index = len(parts) - 2
    parent_pairs = []
    i = 0
    while i + 1 < table_segment_index:
        if parts[i + 1].isdigit():
            parent_pairs.append((parts[i], parts[i + 1]))
            i += 2
        else:
            i += 1
    return parent_pairs


def _extract_item_candidate(path, data):
    parts = [p for p in path.split('/') if p]
    resource_segment = parts[-2]
    requested_id = int(parts[-1])

    preferred_keys = [resource_segment, "items", "data", "results"]
    if resource_segment.endswith("s") and len(resource_segment) > 1:
        preferred_keys.append(resource_segment[:-1])

    candidates = []
    if isinstance(data, list):
        candidates = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        for key in preferred_keys:
            value = data.get(key)
            if isinstance(value, list):
                candidates = [item for item in value if isinstance(item, dict)]
                if candidates:
                    break
        if not candidates:
            candidates = [data]

    if not candidates:
        return None

    for item in candidates:
        try:
            if int(item.get("id")) == requested_id:
                return dict(item)
        except (TypeError, ValueError):
            continue

    return dict(candidates[0])


def _normalize_ai_payload_for_path(path, data):
    """
    Enforces a single-item response shape for item endpoints before saving.
    """
    parts = [p for p in path.split('/') if p]
    if len(parts) < 2 or not parts[-1].isdigit():
        return data

    item = _extract_item_candidate(path, data)
    if not isinstance(item, dict):
        return data

    resource_segment = parts[-2]
    preferred_list_keys = {resource_segment, "items", "data", "results"}
    if resource_segment.endswith("s") and len(resource_segment) > 1:
        preferred_list_keys.add(resource_segment[:-1])

    normalized = {
        key: value
        for key, value in item.items()
        if not (key in preferred_list_keys and isinstance(value, list))
    }
    normalized["id"] = int(parts[-1])

    for parent_resource, parent_id in _parent_pairs_for_path(path):
        normalized[_preferred_fk_field(parent_resource)] = int(parent_id)

    return normalized


def _coerce_int_like(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _looks_like_db_metadata_created_at(value):
    if not isinstance(value, str):
        return False
    # SQLite CURRENT_TIMESTAMP default format: YYYY-MM-DD HH:MM:SS
    return re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value) is not None


def _normalize_public_response(data):
    """
    Normalizes response payloads so cache hits and table hits expose a consistent
    public shape.
    """
    if isinstance(data, list):
        return [_normalize_public_response(item) for item in data]

    if isinstance(data, dict):
        normalized = {}
        for key, value in data.items():
            if key in {"row_id", "source_path"}:
                continue

            cleaned_value = _normalize_public_response(value)

            if cleaned_value is None:
                continue

            if key == "created_at" and _looks_like_db_metadata_created_at(cleaned_value):
                continue

            if key == "id" or key.endswith("_id"):
                cleaned_value = _coerce_int_like(cleaned_value)
            normalized[key] = cleaned_value

        return normalized

    return data


def _schema_validation_error_response(details, duration_seconds):
    response = jsonify({
        "error": "SCHEMA_MISMATCH",
        "message": "AI response does not match the existing resource schema.",
        "status": 422,
        "details": details,
    })
    response.headers['X-Response-Time-Seconds'] = f"{duration_seconds:.2f}"
    return response, 422

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "Tere tulemast API simulatorisse!",
        "instructions": "Siia tuleb hiljem lisainfo",
        "links": "github repo, dokumentatsioon, jne"
    }), 200

@app.route('/delete-all')
def delete_all():
    reset_db.clear_database()
    return jsonify({"message": "All data deleted."}), 200

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/<path:subpath>', methods=['DELETE'])
def delete_resource(subpath):
    full_path = "/" + subpath.strip('/')
    parts = [p for p in full_path.split('/') if p]

    # Allow deletion only for item endpoints that end with a numeric ID.
    if not parts or not parts[-1].isdigit():
        return jsonify({
            "error": "FORBIDDEN",
            "message": "Deletion is allowed only for resource paths ending with a numeric ID.",
            "status": 403,
            "path": full_path,
        }), 403

    body = request.get_json(silent=True) or {}
    reason = body.get("reason") or request.args.get("reason") or "Deleted by API client"

    result = database.delete_resource_and_blacklist(full_path, reason)
    if result.get("error"):
        return jsonify({
            "message": "Failed to delete and blacklist resource.",
            **result,
        }), 500

    return jsonify({
        "message": f"Resource {full_path} deleted and blacklisted.",
        **result,
    }), 200

@app.route('/<path:subpath>')
async def handle_api_request(subpath):
    start_time = time.time()  # Käivitame stopperi
    full_path = "/" + subpath.strip('/')

    # Block known deleted/forbidden paths before any cache/table/AI lookup.
    if database.is_blacklisted(full_path):
        duration = (time.time() - start_time) * 1000
        response = jsonify({
            "error": "RESOURCE_DELETED",
            "message": f"Path '{full_path}' is deleted by user and cannot be generated.",
            "status": 404,
        })
        response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
        return response, 404

    # 1. Otsime andmebaasist
    existing_data = database.get_resource_by_path(full_path)
    
    if existing_data is not None:
        existing_data = _normalize_public_response(existing_data)
        duration = (time.time() - start_time) * 1000  # Arvutame kestuse millisekundites
        print(f"CACHE HIT: {full_path} kätte saadud {duration:.2f} ms-ga.")
        
        # Lisame vastuse päisesse (header), et näha seda ka brauseris/inspektoris
        response = jsonify(existing_data)
        response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
        return response, 200

    # 1.5. If exact cache miss, check dynamic tables (e.g. /books, /books/123)
    dynamic_data = database.get_dynamic_resource_by_path(full_path)
    if dynamic_data is not None:
        dynamic_data = _normalize_public_response(dynamic_data)
        duration = (time.time() - start_time) * 1000
        print(f"TABLE HIT: {full_path} kätte saadud {duration:.2f} ms-ga.")

        response = jsonify(dynamic_data)
        response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
        return response, 200

    if database.has_conflicting_nested_item(full_path):
        duration = (time.time() - start_time) * 1000
        response = jsonify({
            "error": "NOT_FOUND",
            "message": f"Path '{full_path}' does not exist under the requested parent resource.",
            "status": 404,
        })
        response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
        return response, 404

    parent_item_path = _parent_item_path_for_nested_collection(full_path)
    if parent_item_path and not _resource_exists(parent_item_path):
        parent_data = None
        for _ in range(2):
            parent_parent_path, parent_parent_data = _find_parent_context(parent_item_path)
            parent_expected_schema = database.get_existing_schema_for_path(parent_item_path)
            parent_data = await ai_client.get_ai_content(
                parent_item_path,
                parent_path=parent_parent_path,
                parent_data=parent_parent_data,
                expected_schema=parent_expected_schema,
            )
            if "error" not in parent_data:
                parent_data = _normalize_ai_payload_for_path(parent_item_path, parent_data)
                is_valid_parent, parent_mismatch = database.validate_payload_against_existing_schema(
                    parent_item_path,
                    parent_data,
                )
                if not is_valid_parent:
                    parent_data = {
                        "error": "SCHEMA_MISMATCH",
                        "status": 422,
                        "details": parent_mismatch,
                    }
                    continue
                database.save_structured_resource(parent_item_path, parent_data)
                break
        else:
            if isinstance(parent_data, dict) and parent_data.get("error") == "SCHEMA_MISMATCH":
                duration = time.time() - start_time
                return _schema_validation_error_response(parent_data.get("details"), duration)
            duration = time.time() - start_time
            response = jsonify(parent_data)
            response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
            return response, 404

    # 2. Kui pole andmebaasis, siis AI
    print(f"CACHE MISS: {full_path} läheb AI-le...")
    parent_path, parent_data = _find_parent_context(full_path)
    if parent_data is not None:
        print(f"PARENT CONTEXT FOUND: {parent_path}")

    expected_schema = database.get_existing_schema_for_path(full_path)

    new_data = await ai_client.get_ai_content(
        full_path,
        parent_path=parent_path,
        parent_data=parent_data,
        expected_schema=expected_schema,
    )

    if "error" not in new_data:
        new_data = _normalize_ai_payload_for_path(full_path, new_data)

    if "error" not in new_data:
        is_valid, mismatch_details = database.validate_payload_against_existing_schema(full_path, new_data)
        if not is_valid:
            duration = time.time() - start_time
            return _schema_validation_error_response(mismatch_details, duration)
    
    if "error" not in new_data:
        new_data = database.save_structured_resource(full_path, new_data)
    
    duration = time.time() - start_time  # AI puhul mõõdame pigem sekundites
    print(f"AI GENERAATOR: Valmis {duration:.2f} sekundiga.")
    
    response = jsonify(new_data)
    response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
    return response, 200

if __name__ == '__main__':
    # Start the Flask app
    app.run(debug=True, port=5000)