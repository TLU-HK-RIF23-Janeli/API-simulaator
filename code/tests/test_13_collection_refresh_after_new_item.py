from conftest import print_response
import pytest


def test_13_books_collection_refreshes_after_generating_books_6(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    calls_before = ai_mock.await_count

    books_before = client.get("/books")
    print_response("GET /books before /books/6", books_before)
    assert books_before.status_code == 200

    book_6 = client.get("/books/6")
    print_response("GET /books/6 first", book_6)
    assert book_6.status_code == 200
    assert book_6.get_json() == {"id": 6, "title": "Generated Book 6"}
    assert ai_mock.await_count == calls_before + 1

    books_after = client.get("/books")
    print_response("GET /books after /books/6", books_after)
    assert books_after.status_code == 200

    books_json = books_after.get_json()
    assert isinstance(books_json, list)
    assert any(item.get("id") == 6 for item in books_json if isinstance(item, dict))
    assert ai_mock.await_count == calls_before + 1
