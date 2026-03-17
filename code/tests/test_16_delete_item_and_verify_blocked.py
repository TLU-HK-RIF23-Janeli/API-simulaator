from conftest import print_response
import pytest


def test_16_delete_books_1_comments_1_blocks_all_variants(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    # Ensure the comment exists before deleting
    pre = client.get("/books/1/comments/1")
    print_response("GET /books/1/comments/1 before delete", pre)
    assert pre.status_code == 200

    # Delete it
    delete_response = client.delete("/books/1/comments/1")
    print_response("DELETE /books/1/comments/1", delete_response)
    assert delete_response.status_code == 200

    # Exact path is now blocked
    r1 = client.get("/books/1/comments/1")
    print_response("GET /books/1/comments/1 after delete", r1)
    assert r1.status_code == 404

    # Short alias is also blocked
    r2 = client.get("/comments/1")
    print_response("GET /comments/1 after delete", r2)
    assert r2.status_code == 404

    # Same comment id under a different parent is also blocked
    r3 = client.get("/books/2/comments/1")
    print_response("GET /books/2/comments/1 after delete", r3)
    assert r3.status_code == 404
