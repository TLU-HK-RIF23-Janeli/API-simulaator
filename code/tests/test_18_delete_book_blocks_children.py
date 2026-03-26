from conftest import print_response
import pytest


def test_18_delete_book_blocks_item_and_children(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    # Ensure book 999 exists before deleting
    pre = client.get("/books/999")
    print_response("GET /books/999 before delete", pre)
    assert pre.status_code == 200

    # Delete it
    delete_response = client.delete("/books/999")
    print_response("DELETE /books/999", delete_response)
    assert delete_response.status_code == 200

    # The deleted item itself is blocked
    r1 = client.get("/books/999")
    print_response("GET /books/999 after delete", r1)
    assert r1.status_code == 404

    # The collection is still accessible
    r2 = client.get("/books")
    print_response("GET /books after delete", r2)
    assert r2.status_code == 200
    books = r2.get_json()
    assert isinstance(books, list)
    assert not any(item.get("id") == 999 for item in books if isinstance(item, dict))

    # Nested collection under deleted parent is blocked
    r3 = client.get("/books/999/comments")
    print_response("GET /books/999/comments after delete", r3)
    assert r3.status_code == 404

    # Nested item under deleted parent is also blocked
    r4 = client.get("/books/999/comments/3")
    print_response("GET /books/999/comments/3 after delete", r4)
    assert r4.status_code == 404

    # Global /comments collection should no longer contain comments from book 999
    # (fake AI stored those with book_id=999)
    r5 = client.get("/comments")
    print_response("GET /comments after deleting book 999", r5)
    assert r5.status_code == 200
    comments = r5.get_json()
    assert isinstance(comments, list)
    assert not any(item.get("book_id") == 999 for item in comments if isinstance(item, dict))

