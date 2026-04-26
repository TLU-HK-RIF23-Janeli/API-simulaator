import time
import re
import json
from flask import Flask, request, jsonify, render_template
import database
import ai_client
import reset_db

app = Flask(__name__)
app.json.sort_keys = False  # Preserve the order of JSON keys as they are defined in the database

# =============== CORS FIX (lisa siia) ===============
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response
# ====================================================

# On startup, initialize the database
database.init_db()


def _resource_exists(path):
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
    if len(parts) < 3:
        return None, None

    # Trim from right to left: /a/b/c -> /a/b -> /a
    for i in range(len(parts) - 1, 0, -1):
        candidate = "/" + "/".join(parts[:i])

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
        "message": "Resource does not match the existing resource schema.",
        "status": 422,
        "details": details,
    })
    response.headers['X-Response-Time-Seconds'] = f"{duration_seconds:.2f}"
    print(response.get_json())
    return response, 422


def _status_from_error_payload(payload, default_status=400):
    if not isinstance(payload, dict):
        return default_status

    raw_status = payload.get("status")
    try:
        status = int(raw_status)
    except (TypeError, ValueError):
        return default_status

    if status < 100 or status > 599:
        return default_status

    return status


def _conflict_response(full_path, message, details=None):
    response = jsonify({
        "error": "CONFLICT",
        "message": message,
        "status": 409,
        "path": full_path,
    })
    print(response.get_json())
    if details is not None:
        response.get_json()["details"] = details
    return response, 409


def _is_collection_path(path):
    parts = [p for p in path.split('/') if p]
    return bool(parts) and not parts[-1].isdigit()


def _extract_collection_items(path, data):
    resource_segment = [p for p in path.split('/') if p][-1]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        preferred_keys = [resource_segment, "items", "data", "results"]
        if resource_segment.endswith("s") and len(resource_segment) > 1:
            preferred_keys.append(resource_segment[:-1])

        for key in preferred_keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        return [data] if data else []

    return []


def _parse_limit_or_error(limit_raw, full_path):
    if limit_raw is None:
        return None, None

    try:
        parsed = int(limit_raw)
    except (TypeError, ValueError):
        return None, (
            jsonify({
                "error": "BAD_REQUEST",
                "message": "Query parameter 'limit' must be a positive integer.",
                "status": 400,
                "path": full_path,
            }),
            400,
        )

    if parsed <= 0:
        return None, (
            jsonify({
                "error": "BAD_REQUEST",
                "message": "Query parameter 'limit' must be greater than zero.",
                "status": 400,
                "path": full_path,
            }),
            400,
        )

    if not _is_collection_path(full_path):
        return None, (
            jsonify({
                "error": "BAD_REQUEST",
                "message": "Query parameter 'limit' is supported only for collection endpoints.",
                "status": 400,
                "path": full_path,
            }),
            400,
        )

    return parsed, None


def _parse_user_schema_or_error(full_path):
    """
    Parses optional user-provided schema from GET query params.
    Supported forms:
    - ?schema=title,author
    - ?schema=title&schema=author
    """
    try:
        schema_values = request.args.getlist("schema")
    except Exception as exc:
        return None, (
            jsonify({
                "error": "BAD_REQUEST",
                "message": "Failed to parse query parameter 'schema'.",
                "status": 400,
                "path": full_path,
                "details": str(exc),
            }),
            400,
        )

    if not schema_values:
        return None, None

    raw_columns = []
    for value in schema_values:
        if value is None:
            continue
        parts = [part.strip() for part in str(value).split(",")]
        raw_columns.extend([part for part in parts if part])

    normalized = database.normalize_schema_columns(raw_columns)
    if not normalized:
        return None, (
            jsonify({
                "error": "BAD_REQUEST",
                "message": "Query parameter 'schema' must include at least one column name.",
                "status": 400,
                "path": full_path,
            }),
            400,
        )

    # Keep stable required fields in first-generation schema constraints.
    if "id" not in normalized:
        normalized.insert(0, "id")

    for parent_resource, _ in _parent_pairs_for_path(full_path):
        fk_field = _preferred_fk_field(parent_resource)
        if fk_field not in normalized:
            normalized.append(fk_field)

    return normalized, None


def _parse_dynamic_query_params():
    """
    Parses dynamic query parameters while excluding reserved parameters.
    Returned values are normalized for stable filtering/generation behavior.
    """
    reserved_params = {"limit", "schema"}
    parsed = {}

    for raw_key, values in request.args.lists():
        try:
            if raw_key in reserved_params:
                continue

            key = str(raw_key).strip()
            if not key:
                continue

            normalized_values = []
            for value in values:
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    normalized_values.append(text)

            if not normalized_values:
                continue

            if len(normalized_values) == 1:
                parsed[key] = normalized_values[0]
            else:
                parsed[key] = normalized_values
        except Exception:
            # Ignore malformed single query entries but keep valid ones.
            continue

    return parsed


def _to_comparable_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _query_key_candidates(query_key):
    key = str(query_key).strip()
    if not key:
        return []

    candidates = [key]
    if key.endswith("s") and len(key) > 1:
        candidates.append(key[:-1])
    else:
        candidates.append(f"{key}s")

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))


def _value_tokens(value):
    if value is None:
        return []

    if isinstance(value, list):
        tokens = []
        for item in value:
            tokens.extend(_value_tokens(item))
        return tokens

    text = _to_comparable_text(value).strip().lower()
    if not text:
        return []

    # Support common CSV-like storage patterns (e.g. "breakfast, main course").
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]

    return [text]


def _apply_dynamic_query_filters(full_path, data, dynamic_query_params):
    if not dynamic_query_params or not _is_collection_path(full_path):
        return data

    items = _extract_collection_items(full_path, data)
    if not items:
        return []

    normalized_filters = {
        key: value if isinstance(value, list) else [value]
        for key, value in dynamic_query_params.items()
    }

    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue

        matches_all = True
        for key, accepted_values in normalized_filters.items():
            match_field = None
            for candidate_key in _query_key_candidates(key):
                if candidate_key in item:
                    match_field = candidate_key
                    break

            if match_field is None:
                matches_all = False
                break

            item_tokens = set(_value_tokens(item.get(match_field)))
            accepted_texts = {
                _to_comparable_text(value).strip().lower()
                for value in accepted_values
                if _to_comparable_text(value).strip()
            }
            if not item_tokens:
                matches_all = False
                break

            if not item_tokens.intersection(accepted_texts):
                matches_all = False
                break

        if matches_all:
            filtered.append(item)

    return filtered


def _resolve_expected_schema_or_error(path, user_schema):
    """
    Resolves schema used for AI generation.
    Precedence: existing DB schema -> user schema (first generation only) -> empty.
    """
    existing_schema = database.get_existing_schema_for_path(path)
    if existing_schema:
        if user_schema:
            if set(existing_schema) != set(user_schema):
                message = jsonify({
                    "error": "SCHEMA_CONFLICT",
                    "message": "Provided schema conflicts with the existing resource schema.",
                    "status": 409,
                    "path": path,
                    "details": {
                        "existing_schema": existing_schema,
                        "provided_schema": user_schema,
                    },
                })
                print(message.get_json())

                return message, 409
        return existing_schema, None

    if user_schema:
        persisted_schema = database.set_expected_schema_for_path(path, user_schema)
        return persisted_schema, None

    return [], None


async def _handle_collection_limit_request(
    full_path,
    requested_limit,
    start_time,
    user_expected_schema=None,
    dynamic_query_params=None,
):
    # Ensure nested parent exists for endpoints like /books/2/comments?limit=7
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
            status = _status_from_error_payload(parent_data, default_status=404)
            response = jsonify(parent_data)
            response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
            return response, status

    # Build current collection state from table first, then cache fallback.
    current_data = database.get_dynamic_resource_by_path(full_path)

    current_data = _normalize_public_response(current_data) if current_data is not None else []
    current_items = _extract_collection_items(full_path, current_data)
    current_items = _apply_dynamic_query_filters(full_path, current_items, dynamic_query_params)

    missing_count = requested_limit - len(current_items)
    if missing_count > 0:
        parent_path, parent_data = _find_parent_context(full_path)
        expected_schema, schema_error = _resolve_expected_schema_or_error(full_path, user_expected_schema)
        if schema_error is not None:
            return schema_error

        generation_context = {
            "existing_items": current_items,
            "missing_count": missing_count,
            "requested_total": requested_limit,
        }
        if parent_data is not None:
            generation_context["parent_context"] = parent_data

        generated_data = await ai_client.get_ai_content(
            full_path,
            parent_path=parent_path,
            parent_data=generation_context,
            expected_schema=expected_schema,
            requested_count=missing_count,
            dynamic_query_params=dynamic_query_params,
        )

        if "error" in generated_data:
            status = generated_data.get("status", 404)
            response = jsonify(generated_data)
            response.headers['X-Response-Time-Seconds'] = f"{(time.time() - start_time):.2f}"
            return response, status

        is_valid, mismatch_details = database.validate_payload_against_existing_schema(
            full_path,
            generated_data,
            allow_missing_id=True,
        )
        if not is_valid:
            duration = time.time() - start_time
            return _schema_validation_error_response(mismatch_details, duration)

        generated_items = _extract_collection_items(full_path, _normalize_public_response(generated_data))
        for item in generated_items:
            # For collection backfill, ignore AI-provided IDs and let DB assign
            # the next safe ID (prevents reusing deleted/blacklisted IDs).
            if isinstance(item, dict):
                item.pop("id", None)
            database.save_user_resource(full_path, item)

        refreshed = database.get_dynamic_resource_by_path(full_path)
        refreshed = _normalize_public_response(refreshed) if refreshed is not None else []
        current_items = _extract_collection_items(full_path, refreshed)
        current_items = _apply_dynamic_query_filters(full_path, current_items, dynamic_query_params)

    duration = (time.time() - start_time) * 1000
    response = jsonify(current_items[:requested_limit])
    response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
    return response, 200


def _documentation_static_spec():
    return {
        "title": "TI API Simulator",
        "version": "current",
        "base_url": "/",
        "endpoints": [
            {
                "path": "/specification",
                "method": "GET",
                "description": "Returns current simulation specification.",
            },
            {
                "path": "/specification",
                "method": "POST",
                "description": "Sets simulation specification string.",
            },
            {
                "path": "/delete-all",
                "method": "DELETE",
                "description": "Clears all cached/generated data and reinitializes DB.",
            },
            {
                "path": "/<path:subpath>",
                "method": "GET",
                "description": "Reads resource; generates with AI when not found.",
            },
            {
                "path": "/<path:subpath>",
                "method": "POST",
                "description": "Creates item in collection endpoints.",
            },
            {
                "path": "/<path:subpath>",
                "method": "PATCH",
                "description": "Updates existing item endpoint.",
            },
            {
                "path": "/<path:subpath>",
                "method": "DELETE",
                "description": "Deletes item and blacklists path/aliases.",
            },
        ],
        "query_parameters": [
            {
                "name": "limit",
                "applies_to": "Collection GET endpoints",
                "type": "integer > 0",
                "description": "Returns exactly N items; generates missing items if needed.",
            },
            {
                "name": "schema",
                "applies_to": "First generation GET requests",
                "type": "comma separated values or repeated parameter",
                "description": "Constrains generated schema fields.",
            },
            {
                "name": "<any_other_param>",
                "applies_to": "GET collection endpoints",
                "type": "string or repeated parameter",
                "description": "Handled dynamically as filter/constraint and forwarded to AI generation context.",
            },
        ],
        "status_codes": [
            {"status": 200, "meaning": "Success"},
            {"status": 201, "meaning": "Created"},
            {"status": 400, "meaning": "Bad request (query/body validation)"},
            {"status": 403, "meaning": "Forbidden endpoint usage"},
            {"status": 404, "meaning": "Not found or blacklisted"},
            {"status": 405, "meaning": "Method not allowed"},
            {"status": 409, "meaning": "Schema/id/path conflict"},
            {"status": 422, "meaning": "Schema mismatch"},
        ],
    }

def _documentation_state_payload():
    state = database.get_documentation_state_snapshot()
    return {
        "specification": _documentation_static_spec(),
        "active_api_specification": ai_client.get_api_specification(),
        "resources": state.get("resources", []),
        "blacklisted_paths": state.get("blacklisted_paths", []),
        "totals": {
            "resource_count": state.get("resource_count", 0),
            "blacklist_count": state.get("blacklist_count", 0),
        },
        "status": 200,
    }

@app.route('/')
def home():
    return render_template('home.html'), 200

@app.route('/documentation')
def documentation():
    return render_template('documentation.html'), 200


@app.route('/documentation/state', methods=['GET'])
def documentation_state():
    return jsonify(_documentation_state_payload()), 200

@app.route('/specification', methods = ['POST'])
def set_specification():
    content_type = request.headers.get('Content-Type')
    if content_type != 'application/json':
        return jsonify({
            "error": "BAD_REQUEST",
            "message": "Content-Type must be application/json.",
            "status": 400,
        }), 400

    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "error": "BAD_REQUEST",
            "message": "Request body must be valid JSON.",
            "status": 400,
        }), 400

    specification = body.get("specification")
    if not isinstance(specification, str):
        return jsonify({
            "error": "BAD_REQUEST",
            "message": "JSON body must include a 'specification' field of type string.",
            "status": 400,
        }), 400

    normalized_specification = specification.strip()
    if normalized_specification:
        saved_specification = ai_client.save_api_specification(normalized_specification)
        print(f"API specification updated to: {saved_specification}")
        return jsonify({
            "message": "API specification updated successfully.",
            "api_specification": ai_client.get_api_specification(),
            "status": 200,
        }), 200

    ai_client.reset_api_specification()
    print("API specification reset to default from environment.")
    return jsonify({
        "message": "API specification reset to environment default.",
        "api_specification": ai_client.get_api_specification(),
        "status": 200,
    }), 200

@app.route('/specification', methods = ['GET'])
def get_specification():
    API_SPECIFICATION = ai_client.get_api_specification()
    return jsonify({
        "api_specification": API_SPECIFICATION,
        "status": 200,
    }), 200

@app.route('/tester', methods = ['GET'])
def tester():
    return render_template('tester2.html'), 200

@app.route('/delete-all', methods=['DELETE'])
def delete_all():
    reset_db.clear_database()
    database.init_db()
    return jsonify({"message": "All data deleted."}), 200

@app.route('/delete-all', methods=['GET', 'POST', 'PUT', 'PATCH', 'HEAD', 'OPTIONS'])
def delete_all_unsupported_methods():
    return jsonify({
        "error": "METHOD_NOT_ALLOWED",
        "message": "Only DELETE method is allowed for this endpoint.",
        "status": 405,
        "path": "/delete-all",
        "allowed_methods": ["DELETE"],
    }), 405

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

    # Idempotent delete: if already blacklisted/deleted, return success marker.
    if database.is_blacklisted(full_path):
        return jsonify({
            "message": f"Resource {full_path} is already deleted.",
            "path": full_path,
            "already_deleted": True,
            "blacklisted": True,
            "status": 200,
        }), 200

    # Do not blacklist item paths that never existed.
    existing_data = database.get_dynamic_resource_by_path(full_path)
    if existing_data is None:
        return jsonify({
            "error": "NOT_FOUND",
            "message": f"Path '{full_path}' does not exist.",
            "status": 404,
            "path": full_path,
        }), 404

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

@app.route('/<path:subpath>', methods=['POST'])
async def post_resource(subpath):
    start_time = time.time()
    full_path = "/" + subpath.strip('/')
    parts = [p for p in full_path.split('/') if p]

    # Reject POST to item endpoints (cannot POST /books/123, only /books).
    if parts and parts[-1].isdigit():
        return jsonify({
            "error": "FORBIDDEN",
            "message": "POST is not allowed for item endpoints. Use collection paths like /books or /books/1/comments.",
            "status": 403,
            "path": full_path,
        }), 403

    # Require JSON body
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "error": "BAD_REQUEST",
            "message": "POST request requires a valid JSON body.",
            "status": 400,
            "path": full_path,
        }), 400

    # Check if schema exists for this path
    existing_schema = database.get_existing_schema_for_path(full_path)
    if existing_schema:
        # Validate payload against existing schema (allow_missing_id for auto-generation)
        is_valid, mismatch_details = database.validate_payload_against_existing_schema(
            full_path, body, allow_missing_id=True
        )
        if not is_valid:
            duration = time.time() - start_time
            return _schema_validation_error_response(mismatch_details, duration)

    # Save resource (infers and stores schema if this is the first insert)
    saved_data = database.save_user_resource(full_path, body)

    duration = time.time() - start_time
    response = jsonify({
        "message": f"Resource created at {full_path}.",
        "status": 201,
        "path": full_path,
        "data": saved_data,
    })
    response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
    return response, 201


@app.route('/<path:subpath>', methods=['PATCH'])
def patch_resource(subpath):
    start_time = time.time()
    full_path = "/" + subpath.strip('/')
    parts = [p for p in full_path.split('/') if p]

    if not parts or not parts[-1].isdigit():
        return jsonify({
            "error": "FORBIDDEN",
            "message": "PATCH is allowed only for resource paths ending with a numeric ID.",
            "status": 403,
            "path": full_path,
        }), 403

    if database.is_blacklisted(full_path):
        return jsonify({
            "error": "RESOURCE_DELETED",
            "message": f"Path '{full_path}' is deleted by user and cannot be updated.",
            "status": 404,
            "path": full_path,
        }), 404

    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return jsonify({
            "error": "BAD_REQUEST",
            "message": "PATCH request requires a valid JSON object body.",
            "status": 400,
            "path": full_path,
        }), 400

    existing_data = database.get_dynamic_resource_by_path(full_path)
    if existing_data is None:
        return jsonify({
            "error": "NOT_FOUND",
            "message": f"Path '{full_path}' does not exist.",
            "status": 404,
            "path": full_path,
        }), 404

    existing_data = _normalize_public_response(existing_data)
    if not isinstance(existing_data, dict):
        return jsonify({
            "error": "NOT_FOUND",
            "message": f"Path '{full_path}' does not resolve to a single updatable resource.",
            "status": 404,
            "path": full_path,
        }), 404

    path_id = int(parts[-1])
    payload_id = body.get("id")
    if payload_id is not None and _coerce_int_like(payload_id) != path_id:
        return _conflict_response(
            full_path,
            "Payload id must match the resource id in the request path.",
            {"path_id": path_id, "payload_id": payload_id},
        )

    for parent_resource, parent_id in _parent_pairs_for_path(full_path):
        fk_field = _preferred_fk_field(parent_resource)
        payload_fk = body.get(fk_field)
        if payload_fk is not None and _coerce_int_like(payload_fk) != int(parent_id):
            return _conflict_response(
                full_path,
                f"Payload field '{fk_field}' must match the parent resource id in the request path.",
                {"field": fk_field, "path_parent_id": int(parent_id), "payload_parent_id": payload_fk},
            )

    merged_data = dict(existing_data)
    merged_data.update(body)
    merged_data["id"] = path_id
    for parent_resource, parent_id in _parent_pairs_for_path(full_path):
        merged_data[_preferred_fk_field(parent_resource)] = int(parent_id)

    is_valid, mismatch_details = database.validate_payload_against_existing_schema(full_path, merged_data)
    if not is_valid:
        duration = time.time() - start_time
        return _schema_validation_error_response(mismatch_details, duration)

    updated_data = database.update_user_resource(full_path, merged_data)
    if updated_data is None:
        return jsonify({
            "error": "NOT_FOUND",
            "message": f"Path '{full_path}' does not exist.",
            "status": 404,
            "path": full_path,
        }), 404
    if isinstance(updated_data, dict) and updated_data.get("error"):
        return jsonify({
            "error": "UPDATE_FAILED",
            "message": "Failed to update resource.",
            "status": 500,
            "path": full_path,
            "details": updated_data,
        }), 500

    duration = time.time() - start_time
    response = jsonify({
        "message": f"Resource updated at {full_path}.",
        "status": 200,
        "path": full_path,
        "data": updated_data,
    })
    response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
    return response, 200

@app.route('/<path:subpath>', methods=['GET'])
async def handle_api_request(subpath):
    start_time = time.time()  # Start the timer
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

    try:
        limit_values = request.args.getlist("limit")
        if len(limit_values) > 1:
            return jsonify({
                "error": "BAD_REQUEST",
                "message": "Query parameter 'limit' must be provided at most once.",
                "status": 400,
                "path": full_path,
            }), 400

        limit_raw = limit_values[0] if limit_values else None
        requested_limit, limit_error = _parse_limit_or_error(limit_raw, full_path)
        if limit_error is not None:
            return limit_error

        user_expected_schema, schema_parse_error = _parse_user_schema_or_error(full_path)
        if schema_parse_error is not None:
            return schema_parse_error

        dynamic_query_params = _parse_dynamic_query_params()
    except Exception as exc:
        return jsonify({
            "error": "INTERNAL_SERVER_ERROR",
            "message": "Failed to parse query parameters.",
            "status": 500,
            "path": full_path,
            "details": str(exc),
        }), 500

    if requested_limit is not None:
        return await _handle_collection_limit_request(
            full_path,
            requested_limit,
            start_time,
            user_expected_schema=user_expected_schema,
            dynamic_query_params=dynamic_query_params,
        )
    
    if user_expected_schema is not None:
        existing_schema = database.get_existing_schema_for_path(full_path)
        if existing_schema and set(existing_schema) != set(user_expected_schema):
            duration = (time.time() - start_time) * 1000
            response = jsonify({
                "error": "SCHEMA_CONFLICT",
                "message": "Provided schema conflicts with the existing resource schema.",
                "status": 409,
                "path": full_path,
                "details": {
                    "existing_schema": existing_schema,
                    "provided_schema": user_expected_schema,
                },
            })
            print(response.get_json())
            return response, 409

    # 1. Search from the database
    dynamic_data = database.get_dynamic_resource_by_path(full_path)
    if dynamic_data is not None:
        dynamic_data = _normalize_public_response(dynamic_data)
        dynamic_data = _apply_dynamic_query_filters(full_path, dynamic_data, dynamic_query_params)
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

    # 2. If no data found from  the database, generate with AI
    print(f"DATABASE MISS: {full_path} läheb AI-le...")
    parent_path, parent_data = _find_parent_context(full_path)
    if parent_data is not None:
        print(f"PARENT CONTEXT FOUND: {parent_path}")

    expected_schema, schema_error = _resolve_expected_schema_or_error(full_path, user_expected_schema)
    if schema_error is not None:
        return schema_error
    print(f"EXISTING SCHEMA for {full_path}: {expected_schema}")

    new_data = await ai_client.get_ai_content(
        full_path,
        parent_path=parent_path,
        parent_data=parent_data,
        expected_schema=expected_schema,
        dynamic_query_params=dynamic_query_params,
    )

    if not (isinstance(new_data, dict) and new_data.get("error")):
        new_data = _normalize_ai_payload_for_path(full_path, new_data)

    if not (isinstance(new_data, dict) and new_data.get("error")):
        is_valid, mismatch_details = database.validate_payload_against_existing_schema(
            full_path,
            new_data,
            allow_missing_id=_is_collection_path(full_path),
        )
        if not is_valid:
            duration = time.time() - start_time
            return _schema_validation_error_response(mismatch_details, duration)
    
    if not (isinstance(new_data, dict) and new_data.get("error")):
        new_data = database.save_structured_resource(full_path, new_data)
    
    duration = time.time() - start_time  # AI time + any DB save time in second
    print(f"AI GENERAATOR: Valmis {duration:.2f} sekundiga.")
    
    if isinstance(new_data, dict) and new_data.get("error"):
        status = _status_from_error_payload(new_data, default_status=400)
        response = jsonify(new_data)
        response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
        return response, status

    response = jsonify(new_data)
    response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
    return response, 200

@app.route('/<path:subpath>', methods=['PUT', 'HEAD', 'OPTIONS'])
def unsupported_method(subpath):
    full_path = "/" + subpath.strip('/')
    return jsonify({
        "error": "METHOD_NOT_ALLOWED",
        "message": f"HTTP method not supported for this endpoint.",
        "status": 405,
        "path": full_path,
        "allowed_methods": ["GET", "POST", "PATCH", "DELETE"],
    }), 405

if __name__ == '__main__':
    # Start the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)