from conftest import print_response
import pytest


def test_06_get_books_2_comments_1_returns_404_without_ai(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    # Requires prior ordered state so comments under books/1 and books/2 already exist.
    if ai_mock.await_count < 3:
        pytest.skip("Requires test_01, test_02 and test_03 state. Run via tests/run_ordered_endpoint_tests.py")

    ai_calls_before = ai_mock.await_count
    response = client.get("/books/2/comments/1")
    print_response("GET /books/2/comments/1 once", response)

    assert response.status_code == 404
    assert ai_mock.await_count == ai_calls_before
