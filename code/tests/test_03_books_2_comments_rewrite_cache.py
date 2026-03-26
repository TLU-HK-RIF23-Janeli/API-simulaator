from conftest import print_response
import pytest


def test_03_get_books_2_comments_duplicate_ids_are_rewritten_then_cached(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 2:
        pytest.skip("Requires test_01 and test_02 state. Run via tests/run_ordered_endpoint_tests.py")

    first_response = client.get("/books/2/comments")
    print_response("GET /books/2/comments first", first_response)
    assert first_response.status_code == 200

    first_json = first_response.get_json()
    assert "comments" in first_json
    assert [item["id"] for item in first_json["comments"]] == [3, 4]
    assert [item["book_id"] for item in first_json["comments"]] == [2, 2]
    assert ai_mock.await_count == 3

    second_response = client.get("/books/2/comments")
    print_response("GET /books/2/comments second", second_response)
    assert second_response.status_code == 200
    assert second_response.get_json() == first_json
    assert ai_mock.await_count == 3
