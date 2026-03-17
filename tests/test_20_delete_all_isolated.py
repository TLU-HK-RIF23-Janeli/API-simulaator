from conftest import print_response


def test_20_delete_all_resets_cache_and_blacklist(isolated_test_env):
    client = isolated_test_env["client"]
    ai_mock = isolated_test_env["ai_mock"]

    first_books = client.get("/books")
    print_response("GET /books before /delete-all", first_books)
    assert first_books.status_code == 200
    assert ai_mock.await_count == 1

    first_book6 = client.get("/books/6")
    print_response("GET /books/6 before delete", first_book6)
    assert first_book6.status_code == 200
    assert ai_mock.await_count == 2

    deleted = client.delete("/books/6")
    print_response("DELETE /books/6", deleted)
    assert deleted.status_code == 200

    blocked = client.get("/books/6")
    print_response("GET /books/6 after delete", blocked)
    assert blocked.status_code == 404

    wipe_all = client.delete("/delete-all")
    print_response("DELETE /delete-all", wipe_all)
    assert wipe_all.status_code == 200

    books_after_wipe = client.get("/books")
    print_response("GET /books after /delete-all", books_after_wipe)
    assert books_after_wipe.status_code == 200
    assert ai_mock.await_count == 3

    # If blacklist was reset, /books/6 can be generated again.
    book6_after_wipe = client.get("/books/6")
    print_response("GET /books/6 after /delete-all", book6_after_wipe)
    assert book6_after_wipe.status_code == 200
    assert ai_mock.await_count == 4
