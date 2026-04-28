def test_25_documentation_state_has_static_sections(isolated_test_env):
    client = isolated_test_env["client"]

    response = client.get("/documentation/state")
    assert response.status_code == 200

    body = response.get_json()
    assert body["status"] == 200
    assert "specification" in body
    assert "endpoints" in body["specification"]
    assert "query_parameters" in body["specification"]
    assert "status_codes" in body["specification"]
    assert "resources" in body
    assert "blacklisted_paths" in body
    assert "totals" in body


def test_25_documentation_state_includes_live_resources_and_blacklist(isolated_test_env):
    client = isolated_test_env["client"]

    seed_books = client.get("/books")
    assert seed_books.status_code == 200

    seed_comments = client.get("/books/1/comments")
    assert seed_comments.status_code == 200

    delete_comment = client.delete("/books/1/comments/1")
    assert delete_comment.status_code == 200

    state_response = client.get("/documentation/state")
    assert state_response.status_code == 200
    state = state_response.get_json()

    resources_by_name = {
        resource["resource"]: resource
        for resource in state["resources"]
    }

    assert "books" in resources_by_name
    assert "comments" in resources_by_name

    comments_fields = {
        field["name"]: field["inferred_type"]
        for field in resources_by_name["comments"]["fields"]
    }
    assert comments_fields["id"] == "integer"
    assert comments_fields["book_id"] == "integer"

    blacklist_paths = {entry["path"] for entry in state["blacklisted_paths"]}
    assert "/books/1/comments/1" in blacklist_paths
    assert "/comments/1" in blacklist_paths
    assert state["totals"]["blacklist_count"] >= 2
