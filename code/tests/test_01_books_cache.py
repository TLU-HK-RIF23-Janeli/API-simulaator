from conftest import print_response


def test_01_get_books_twice_uses_ai_then_cache(ordered_test_env):
    client = ordered_test_env["client"]
    ai_mock = ordered_test_env["ai_mock"]
    books_payload = ordered_test_env["books_payload"]

    first_response = client.get("/books")
    print_response("GET /books first", first_response)
    assert first_response.status_code == 200
    assert first_response.get_json() == books_payload
    assert ai_mock.await_count == 1

    second_response = client.get("/books")
    print_response("GET /books second", second_response)
    assert second_response.status_code == 200
    assert second_response.get_json() == books_payload
    assert ai_mock.await_count == 1
