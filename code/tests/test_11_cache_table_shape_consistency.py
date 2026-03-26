from conftest import print_response
import pytest


def test_11_cache_and_table_hits_have_consistent_core_shape(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 2:
        pytest.skip("Requires test_01 and test_02 state. Run via tests/run_ordered_endpoint_tests.py")

    calls_before = ai_mock.await_count

    alias_response = client.get("/comments/1")
    print_response("GET /comments/1 consistency", alias_response)
    assert alias_response.status_code == 200

    nested_response = client.get("/books/1/comments/1")
    print_response("GET /books/1/comments/1 consistency", nested_response)
    assert nested_response.status_code == 200

    alias_json = alias_response.get_json()
    nested_json = nested_response.get_json()

    assert alias_json["id"] == 1
    assert alias_json["book_id"] == 1
    assert nested_json["id"] == 1
    assert nested_json["book_id"] == 1
    assert alias_json["content"] == nested_json["content"]

    assert nested_json == alias_json

    assert "row_id" not in alias_json
    assert "source_path" not in alias_json
    assert "row_id" not in nested_json
    assert "source_path" not in nested_json

    assert ai_mock.await_count == calls_before
