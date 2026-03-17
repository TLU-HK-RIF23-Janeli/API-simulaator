from conftest import print_response
import pytest


def test_02_get_books_1_comments_twice_uses_ai_then_cache(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]
    comments_payload = ordered_test_env["comments_payload"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires test_01 state. Run via tests/run_ordered_endpoint_tests.py")

    first_response = client.get("/books/1/comments")
    print_response("GET /books/1/comments first", first_response)
    assert first_response.status_code == 200
    assert first_response.get_json() == comments_payload
    assert ai_mock.await_count == 2

    second_response = client.get("/books/1/comments")
    print_response("GET /books/1/comments second", second_response)
    assert second_response.status_code == 200
    assert second_response.get_json() == comments_payload
    assert ai_mock.await_count == 2

    kwargs = ai_mock.await_args_list[1].kwargs
    assert kwargs.get("parent_path") == "/books/1"
