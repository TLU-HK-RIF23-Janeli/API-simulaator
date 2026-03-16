from conftest import print_response
import pytest


def test_09_get_articles_2002_normalizes_malformed_ai_item(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 3:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    calls_before = ai_mock.await_count

    first_response = client.get("/articles/2002")
    print_response("GET /articles/2002 first", first_response)
    assert first_response.status_code == 200

    first_json = first_response.get_json()
    assert first_json["id"] == 2002
    assert first_json["title"] == "An insightful read that captivates the imagination."
    assert first_json["author"] == "Alice Johnson"
    assert "articles" not in first_json
    assert ai_mock.await_count == calls_before + 1

    second_response = client.get("/articles/2002")
    print_response("GET /articles/2002 second", second_response)
    assert second_response.status_code == 200
    assert second_response.get_json() == first_json
    assert ai_mock.await_count == calls_before + 1
