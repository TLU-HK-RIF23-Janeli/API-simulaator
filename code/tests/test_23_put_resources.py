from conftest import print_response


def test_put_updates_existing_item_and_preserves_omitted_fields(isolated_test_env):
    client = isolated_test_env["client"]

    books_before = client.get("/books")
    print_response("GET /books before PUT", books_before)
    assert books_before.status_code == 200

    response = client.put("/books/1", json={"title": "Refactoring"})
    print_response("PUT /books/1 partial update", response)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == 200
    assert body["data"] == {"id": 1, "title": "Refactoring"}

    item_after = client.get("/books/1")
    print_response("GET /books/1 after PUT", item_after)
    assert item_after.status_code == 200
    assert item_after.get_json() == {"id": 1, "title": "Refactoring"}

    books_after = client.get("/books")
    print_response("GET /books after PUT", books_after)
    assert books_after.status_code == 200
    books_json = books_after.get_json()
    assert any(
        item.get("id") == 1 and item.get("title") == "Refactoring"
        for item in books_json
        if isinstance(item, dict)
    )


def test_put_updates_nested_item_and_refreshes_alias_views(isolated_test_env):
    client = isolated_test_env["client"]

    books_before = client.get("/books")
    print_response("GET /books before nested PUT", books_before)
    assert books_before.status_code == 200

    comments_before = client.get("/books/1/comments")
    print_response("GET /books/1/comments before PUT", comments_before)
    assert comments_before.status_code == 200

    response = client.put("/books/1/comments/1", json={"content": "Updated comment"})
    print_response("PUT /books/1/comments/1 partial update", response)

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"] == {"id": 1, "book_id": 1, "content": "Updated comment"}

    alias_after = client.get("/comments/1")
    print_response("GET /comments/1 after PUT", alias_after)
    assert alias_after.status_code == 200
    assert alias_after.get_json() == {"id": 1, "book_id": 1, "content": "Updated comment"}

    collection_after = client.get("/books/1/comments")
    print_response("GET /books/1/comments after PUT", collection_after)
    assert collection_after.status_code == 200
    items = collection_after.get_json()
    assert any(
        item.get("id") == 1 and item.get("content") == "Updated comment"
        for item in items
        if isinstance(item, dict)
    )


def test_put_to_collection_returns_403(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.put("/books", json={"title": "Nope"})
    print_response("PUT /books", response)

    assert response.status_code == 403
    body = response.get_json()
    assert body["error"] == "FORBIDDEN"


def test_put_without_json_object_returns_400(isolated_test_env):
    client = isolated_test_env["client"]

    client.get("/books")

    response = client.put("/books/1", data="not json", content_type="application/json")
    print_response("PUT /books/1 with invalid JSON", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_put_nonexistent_item_returns_404(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.put("/books/999", json={"title": "Missing"})
    print_response("PUT /books/999", response)

    assert response.status_code == 404
    body = response.get_json()
    assert body["error"] == "NOT_FOUND"


def test_put_deleted_item_returns_404(isolated_test_env):
    client = isolated_test_env["client"]

    created = client.post("/books", json={"title": "Disposable"})
    print_response("POST /books before delete+put", created)
    assert created.status_code == 201

    deleted = client.delete("/books/1")
    print_response("DELETE /books/1 before PUT", deleted)
    assert deleted.status_code == 200

    response = client.put("/books/1", json={"title": "Restored"})
    print_response("PUT /books/1 after delete", response)

    assert response.status_code == 404
    body = response.get_json()
    assert body["error"] == "RESOURCE_DELETED"


def test_put_rejects_conflicting_payload_id(isolated_test_env):
    client = isolated_test_env["client"]

    client.get("/books")

    response = client.put("/books/1", json={"id": 2, "title": "Mismatch"})
    print_response("PUT /books/1 with conflicting id", response)

    assert response.status_code == 409
    body = response.get_json()
    assert body["error"] == "CONFLICT"


def test_put_rejects_conflicting_parent_fk(isolated_test_env):
    client = isolated_test_env["client"]

    books_before = client.get("/books")
    print_response("GET /books before nested FK conflict", books_before)
    assert books_before.status_code == 200

    client.get("/books/1/comments")

    response = client.put("/books/1/comments/1", json={"book_id": 2, "content": "Mismatch"})
    print_response("PUT /books/1/comments/1 with conflicting book_id", response)

    assert response.status_code == 409
    body = response.get_json()
    assert body["error"] == "CONFLICT"


def test_put_rejects_unknown_fields_outside_schema(isolated_test_env):
    client = isolated_test_env["client"]

    client.get("/books")

    response = client.put("/books/1", json={"pages": {"count": 320}})
    print_response("PUT /books/1 with unknown field", response)

    assert response.status_code == 422
    body = response.get_json()
    assert body["error"] == "SCHEMA_MISMATCH"
    assert "pages" in body["details"]["unknown_columns"]