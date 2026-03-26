from conftest import print_response
import pytest


def test_05_get_comments_1_first_try_does_not_go_to_ai(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    # Requires test_02 to have populated comment aliases/table rows first.
    if ai_mock.await_count < 2:
        pytest.skip("Requires test_01 and test_02 state. Run via tests/run_ordered_endpoint_tests.py")

    ai_calls_before = ai_mock.await_count
    response = client.get("/comments/1")
    print_response("GET /comments/1 once", response)

    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["id"] in (1, "1")
    assert response_json["book_id"] in (1, "1")
    assert response_json["content"] == "Excellent read."
    assert ai_mock.await_count == ai_calls_before
