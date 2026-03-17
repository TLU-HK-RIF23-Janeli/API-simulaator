from conftest import print_response
import pytest


def test_17_deleted_comment_absent_from_collections(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 1:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    # Collection under the parent book should not contain comment 1
    r1 = client.get("/books/1/comments")
    print_response("GET /books/1/comments after deleting comment 1", r1)
    assert r1.status_code == 200
    items = r1.get_json()
    assert isinstance(items, list)
    assert not any(item.get("id") == 1 for item in items if isinstance(item, dict))

    # Short alias collection should also not contain comment 1
    r2 = client.get("/comments")
    print_response("GET /comments after deleting comment 1", r2)
    assert r2.status_code == 200
    items2 = r2.get_json()
    assert isinstance(items2, list)
    assert not any(item.get("id") == 1 for item in items2 if isinstance(item, dict))
