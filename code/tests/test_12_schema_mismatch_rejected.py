from conftest import print_response
import pytest


def test_12_existing_schema_mismatch_returns_422_and_not_saved(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 3:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    original_side_effect = ai_mock.side_effect

    async def schema_side_effect(path, parent_path=None, parent_data=None, expected_schema=None):
        if path == "/planes/1":
            return {"id": 1, "name": "Plane One", "owner": "Alice"}
        if path == "/planes/2":
            return {"id": 2, "name": "Plane Two", "operator": "Bob"}
        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
        )

    ai_mock.side_effect = schema_side_effect

    try:
        calls_before = ai_mock.await_count

        first = client.get("/planes/1")
        print_response("GET /planes/1 first", first)
        assert first.status_code == 200
        assert first.get_json() == {"id": 1, "name": "Plane One", "owner": "Alice"}
        assert ai_mock.await_count == calls_before + 1

        mismatch = client.get("/planes/2")
        print_response("GET /planes/2 mismatch", mismatch)
        assert mismatch.status_code == 422
        mismatch_json = mismatch.get_json()
        assert mismatch_json["error"] == "SCHEMA_MISMATCH"
        assert "operator" in mismatch_json["details"]["unknown_columns"]
        assert ai_mock.await_count == calls_before + 2

        # Not saved: second call should try AI again and fail the same way.
        mismatch_again = client.get("/planes/2")
        print_response("GET /planes/2 mismatch again", mismatch_again)
        assert mismatch_again.status_code == 422
        assert ai_mock.await_count == calls_before + 3
    finally:
        ai_mock.side_effect = original_side_effect
