from conftest import print_response


def test_24_user_schema_is_passed_to_ai_on_first_generation(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    original_side_effect = ai_mock.side_effect
    captured_expected_schema = []

    async def schema_capture_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/movies":
            captured_expected_schema.append(expected_schema)
            return {
                "movies": [
                    {"title": "The Matrix", "genre": "Sci-Fi"},
                    {"title": "Arrival", "genre": "Sci-Fi"},
                ]
            }

        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = schema_capture_side_effect

    try:
        response = client.get("/movies?schema=title,genre")
        print_response("GET /movies?schema=title,genre", response)

        assert response.status_code == 200
        assert captured_expected_schema == [["id", "title", "genre"]]
    finally:
        ai_mock.side_effect = original_side_effect


def test_24_user_schema_conflict_with_existing_schema_returns_409(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    original_side_effect = ai_mock.side_effect

    async def schema_conflict_side_effect(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/planes":
            return {
                "planes": [
                    {"name": "Falcon", "owner": "Alice"},
                ]
            }

        return await original_side_effect(
            path,
            parent_path=parent_path,
            parent_data=parent_data,
            expected_schema=expected_schema,
            requested_count=requested_count,
        )

    ai_mock.side_effect = schema_conflict_side_effect

    try:
        seed = client.get("/planes?schema=name,owner")
        print_response("GET /planes?schema=name,owner", seed)
        assert seed.status_code == 200

        calls_after_seed = ai_mock.await_count

        conflict = client.get("/planes/2?schema=name,operator")
        print_response("GET /planes/2?schema=name,operator", conflict)

        assert conflict.status_code == 409
        body = conflict.get_json()
        assert body["error"] == "SCHEMA_CONFLICT"
        assert ai_mock.await_count == calls_after_seed
    finally:
        ai_mock.side_effect = original_side_effect
