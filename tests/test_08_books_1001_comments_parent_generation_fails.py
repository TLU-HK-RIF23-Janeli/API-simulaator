from conftest import print_response
import pytest


def test_08_get_books_1001_comments_parent_generation_failure(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 3:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    async def always_fail_parent(path, parent_path=None, parent_data=None, expected_schema=None):
        if path == "/books/1001":
            return {
                "error": "Not Found",
                "message": "Book with ID '1001' not found.",
                "status": 404,
            }
        if path == "/books/1001/comments":
            return {
                "comments": [
                    {"id": 1, "book_id": 1001, "content": "Should never be reached"}
                ]
            }
        return {"error": "unexpected test path", "path": path}

    original_side_effect = ai_mock.side_effect
    ai_mock.side_effect = always_fail_parent

    try:
        calls_before = ai_mock.await_count
        first_response = client.get("/books/1001/comments")
        print_response("GET /books/1001/comments first", first_response)

        assert first_response.status_code == 404
        first_json = first_response.get_json()
        assert first_json["error"] == "Not Found"
        assert first_json["status"] == 404
        assert ai_mock.await_count == calls_before + 2

        # If parent was not persisted, next call should repeat parent retries.
        second_response = client.get("/books/1001/comments")
        print_response("GET /books/1001/comments second", second_response)

        assert second_response.status_code == 404
        assert ai_mock.await_count == calls_before + 4
    finally:
        ai_mock.side_effect = original_side_effect
