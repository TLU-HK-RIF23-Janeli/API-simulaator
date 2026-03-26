from conftest import print_response
import pytest


def test_07_get_books_999_comments_generates_parent_and_persists(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 3:
        pytest.skip("Requires test_01..test_03 state. Run via tests/run_ordered_endpoint_tests.py")

    ai_calls_before = ai_mock.await_count

    first_response = client.get("/books/999/comments")
    print_response("GET /books/999/comments first", first_response)
    assert first_response.status_code == 200

    first_json = first_response.get_json()
    assert "comments" in first_json
    assert [item["id"] for item in first_json["comments"]] == [5, 6]
    assert [item["book_id"] for item in first_json["comments"]] == [999, 999]
    assert ai_mock.await_count == ai_calls_before + 3

    parent_response = client.get("/books/999")
    print_response("GET /books/999 after nested generation", parent_response)
    assert parent_response.status_code == 200
    assert parent_response.get_json() == {"id": 999, "title": "Generated Book 999"}
    assert ai_mock.await_count == ai_calls_before + 3

    second_response = client.get("/books/999/comments")
    print_response("GET /books/999/comments second", second_response)
    assert second_response.status_code == 200
    assert second_response.get_json() == first_json
    assert ai_mock.await_count == ai_calls_before + 3
