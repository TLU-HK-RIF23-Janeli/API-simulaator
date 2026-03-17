from conftest import print_response


def test_post_to_collection_infers_schema(isolated_test_env):
    client = isolated_test_env["client"]

    payload = {
        "title": "User Created Book",
        "author": "Jane Doe",
    }

    response = client.post("/books", json=payload)
    print_response("POST /books with user payload", response)

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == 201
    assert body["path"] == "/books"
    assert "data" in body
    saved = body["data"]
    assert saved.get("title") == "User Created Book"
    assert saved.get("author") == "Jane Doe"


def test_post_without_json_body_returns_400(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.post("/books", data="not json")
    print_response("POST /books with non-JSON body", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_post_to_item_endpoint_returns_403(isolated_test_env):
    client = isolated_test_env["client"]

    payload = {"title": "Book"}

    response = client.post("/books/123", json=payload)
    print_response("POST /books/123", response)

    assert response.status_code == 403
    body = response.get_json()
    assert body["error"] == "FORBIDDEN"


def test_post_respects_existing_schema(isolated_test_env):
    client = isolated_test_env["client"]

    # First POST defines schema
    first_payload = {
        "title": "First Book",
        "isbn": "123-456",
    }
    first = client.post("/articles", json=first_payload)
    print_response("POST /articles first", first)
    assert first.status_code == 201

    # Second POST must match schema
    second_payload = {
        "title": "Second Book",
        "unknown_field": "should fail",
    }
    second = client.post("/articles", json=second_payload)
    print_response("POST /articles second (schema mismatch)", second)

    assert second.status_code == 422
    body = second.get_json()
    assert body["error"] == "SCHEMA_MISMATCH"


def test_post_requires_all_schema_columns(isolated_test_env):
    client = isolated_test_env["client"]

    # First POST defines schema with title and author
    first_payload = {
        "title": "First Book",
        "author": "Author A",
    }
    first = client.post("/novels", json=first_payload)
    print_response("POST /novels first", first)
    assert first.status_code == 201

    # Second POST missing author should fail (but id is optional/auto-generated)
    second_payload = {
        "title": "Second Book",
    }
    second = client.post("/novels", json=second_payload)
    print_response("POST /novels second (missing author)", second)

    assert second.status_code == 422
    body = second.get_json()
    assert body["error"] == "SCHEMA_MISMATCH"
    details = body.get("details", {})
    assert "author" in details.get("missing_columns", [])


def test_post_with_compatible_schema_succeeds(isolated_test_env):
    client = isolated_test_env["client"]

    # First POST defines schema
    first_payload = {
        "title": "First Item",
        "category": "science",
    }
    first = client.post("/products", json=first_payload)
    print_response("POST /products first", first)
    assert first.status_code == 201

    # Second POST with same fields should succeed
    second_payload = {
        "title": "Second Item",
        "category": "tech",
    }
    second = client.post("/products", json=second_payload)
    print_response("POST /products second", second)

    assert second.status_code == 201
    body = second.get_json()
    assert body["data"]["title"] == "Second Item"
