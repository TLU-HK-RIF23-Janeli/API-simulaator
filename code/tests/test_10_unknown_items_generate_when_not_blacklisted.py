from conftest import print_response
import pytest


def test_10_unknown_items_generate_when_not_blacklisted(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]

    if ai_mock.await_count < 3:
        pytest.skip("Requires ordered state. Run via tests/run_ordered_endpoint_tests.py")

    original_side_effect = ai_mock.side_effect

    async def contract_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None, dynamic_query_params=None):
        if path == "/books/424242":
            return {
                "id": 424242,
                "title": "Generated Top Level Book",
            }
        if path == "/books/515151/comments/616161":
            return {
                "id": 616161,
                "book_id": 0,
                "content": "Generated child item",
            }
        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
            dynamic_query_params=dynamic_query_params
        )

    ai_mock.side_effect = contract_side_effect

    try:
        calls_before = ai_mock.await_count

        top_first = client.get("/books/424242")
        print_response("GET /books/424242 first", top_first)
        assert top_first.status_code == 200
        assert top_first.get_json() == {
            "id": 424242,
            "title": "Generated Top Level Book",
        }
        assert ai_mock.await_count == calls_before + 1

        top_second = client.get("/books/424242")
        print_response("GET /books/424242 second", top_second)
        assert top_second.status_code == 200
        assert top_second.get_json() == {
            "id": 424242,
            "title": "Generated Top Level Book",
        }
        assert ai_mock.await_count == calls_before + 1

        child_first = client.get("/books/515151/comments/616161")
        print_response("GET /books/515151/comments/616161 first", child_first)
        assert child_first.status_code == 200
        child_first_json = child_first.get_json()
        assert child_first_json["id"] == 616161
        assert child_first_json["book_id"] == 515151
        assert child_first_json["content"] == "Generated child item"
        assert ai_mock.await_count == calls_before + 2

        child_second = client.get("/books/515151/comments/616161")
        print_response("GET /books/515151/comments/616161 second", child_second)
        assert child_second.status_code == 200
        assert child_second.get_json() == child_first_json
        assert ai_mock.await_count == calls_before + 2
    finally:
        ai_mock.side_effect = original_side_effect
