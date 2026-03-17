from conftest import print_response


async def _limit_ai_side_effect(original_side_effect, requested_counts, path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
    if path == "/books" and requested_count is not None:
        requested_counts.append(requested_count)
        return {
            "books": [
                {"title": f"Generated Book {i}"}
                for i in range(1, requested_count + 1)
            ]
        }

    return await original_side_effect(
        path,
        parent_path=parent_path,
        parent_data=parent_data,
        expected_schema=expected_schema,
    )


def test_limit_generates_only_missing_items(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    first = client.get("/books")
    print_response("GET /books initial", first)
    assert first.status_code == 200
    assert ai_mock.await_count == 1

    original_side_effect = ai_mock.side_effect
    requested_counts = []

    async def wrapped_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        return await _limit_ai_side_effect(
            original_side_effect,
            requested_counts,
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = wrapped_side_effect

    limited = client.get("/books?limit=7")
    print_response("GET /books?limit=7", limited)
    assert limited.status_code == 200

    books = limited.get_json()
    assert isinstance(books, list)
    assert len(books) == 7
    assert requested_counts == [5]
    assert ai_mock.await_count == 2


def test_limit_is_rejected_for_item_endpoints(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/books/1?limit=2")
    print_response("GET /books/1?limit=2", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_limit_smaller_than_existing_returns_truncated_collection(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    # Seed the collection to 5 items via user POST (no AI calls expected).
    for i in range(1, 6):
        created = client.post("/books", json={"title": f"Posted Book {i}", "author": "User"})
        assert created.status_code == 201

    assert ai_mock.await_count == 0

    # Request a smaller limit. This should only truncate and must not call AI again.
    smaller = client.get("/books?limit=3")
    print_response("GET /books?limit=3", smaller)
    assert smaller.status_code == 200

    books = smaller.get_json()
    assert isinstance(books, list)
    assert len(books) == 3
    assert ai_mock.await_count == 0


def test_limit_zero_returns_bad_request(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/books?limit=0")
    print_response("GET /books?limit=0", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_limit_negative_returns_bad_request(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/books?limit=-1")
    print_response("GET /books?limit=-1", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_limit_non_numeric_returns_bad_request(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/books?limit=abc")
    print_response("GET /books?limit=abc", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_limit_repeated_parameter_returns_bad_request(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/books?limit=3&limit=5")
    print_response("GET /books?limit=3&limit=5", response)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "BAD_REQUEST"


def test_limit_nested_collection_with_existing_parent(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    # Make /books/1 exist first via collection fetch.
    pre = client.get("/books")
    assert pre.status_code == 200

    original_side_effect = ai_mock.side_effect
    requested_counts = []

    async def wrapped_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/books/1/comments" and requested_count is not None:
            requested_counts.append(requested_count)
            return {
                "comments": [
                    {"content": f"Generated comment {i}"}
                    for i in range(1, requested_count + 1)
                ]
            }

        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = wrapped_side_effect

    response = client.get("/books/1/comments?limit=7")
    print_response("GET /books/1/comments?limit=7", response)

    assert response.status_code == 200
    items = response.get_json()
    assert isinstance(items, list)
    assert len(items) == 7
    assert requested_counts == [7]


def test_limit_nested_collection_autogenerates_missing_parent(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    original_side_effect = ai_mock.side_effect
    requested_counts = []

    async def wrapped_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/books/999/comments" and requested_count is not None:
            requested_counts.append(requested_count)
            return {
                "comments": [
                    {"content": f"Generated nested comment {i}"}
                    for i in range(1, requested_count + 1)
                ]
            }

        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = wrapped_side_effect

    response = client.get("/books/999/comments?limit=7")
    print_response("GET /books/999/comments?limit=7", response)

    assert response.status_code == 200
    items = response.get_json()
    assert isinstance(items, list)
    assert len(items) == 7
    assert requested_counts == [7]

    # Parent should now exist because nested limit flow auto-generated it.
    parent = client.get("/books/999")
    print_response("GET /books/999 after nested limit", parent)
    assert parent.status_code == 200


def test_limit_backfill_skips_blacklisted_ids(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    # Create 9 books (ids 1..9), then delete id 9 to blacklist it.
    for i in range(1, 10):
        created = client.post("/books", json={"title": f"Book {i}", "author": "User"})
        assert created.status_code == 201

    deleted = client.delete("/books/9")
    print_response("DELETE /books/9", deleted)
    assert deleted.status_code == 200

    original_side_effect = ai_mock.side_effect
    requested_counts = []

    async def wrapped_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/books" and requested_count is not None:
            requested_counts.append(requested_count)
            # Reproduce bug: AI tries to reuse a deleted/blacklisted id.
            return {"books": [{"id": 9, "title": "Backfilled Book", "author": "AI"}]}

        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = wrapped_side_effect

    limited = client.get("/books?limit=9")
    print_response("GET /books?limit=9 after deleting /books/9", limited)
    assert limited.status_code == 200

    books = limited.get_json()
    assert isinstance(books, list)
    assert len(books) == 9
    assert requested_counts == [1]

    ids = [item.get("id") for item in books if isinstance(item, dict)]
    assert 9 not in ids
    assert 10 in ids
