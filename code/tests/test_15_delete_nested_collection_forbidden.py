from conftest import print_response
import pytest


def test_15_delete_nested_collection_returns_403(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    response = client.delete("/books/1/comments")
    print_response("DELETE /books/1/comments", response)

    assert response.status_code == 403
    body = response.get_json()
    assert body["error"] == "FORBIDDEN"
