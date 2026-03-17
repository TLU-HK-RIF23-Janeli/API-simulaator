from conftest import print_response


def test_19_delete_nonexistent_resource_is_stable(ordered_test_env):
    client = ordered_test_env["client"]

    target = "/books/555555"

    delete_response = client.delete(target)
    print_response("DELETE /books/555555", delete_response)
    assert delete_response.status_code == 404

    body = delete_response.get_json()
    assert body.get("error") == "NOT_FOUND"
    assert body.get("path") == target


def test_19_double_delete_is_idempotent(ordered_test_env):
    client = ordered_test_env["client"]

    # Ensure resource exists first (already used in prior ordered tests)
    pre = client.get("/books/6")
    print_response("GET /books/6 before double delete", pre)
    assert pre.status_code == 200

    first = client.delete("/books/6")
    print_response("DELETE /books/6 first", first)
    assert first.status_code == 200

    second = client.delete("/books/6")
    print_response("DELETE /books/6 second", second)
    assert second.status_code == 200

    body_second = second.get_json()
    assert body_second.get("already_deleted") is True

    # Still blocked after repeated deletes.
    post = client.get("/books/6")
    print_response("GET /books/6 after double delete", post)
    assert post.status_code == 404
