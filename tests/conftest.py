import importlib
import json
from unittest.mock import AsyncMock

import pytest


def print_response(label, response):
    print(f"\n[{label}] status={response.status_code}")
    print(json.dumps(response.get_json(), ensure_ascii=False, indent=2))


def _build_test_env(db_path):
    import database
    import reset_db

    database.DB_NAME = str(db_path)
    reset_db.DB_NAME = str(db_path)
    database.init_db()

    import main

    main = importlib.reload(main)
    main.database.DB_NAME = str(db_path)
    main.reset_db.DB_NAME = str(db_path)
    main.database.init_db()
    main.app.config["TESTING"] = True

    books_payload = {
        "books": [
            {"id": 1, "title": "Clean Architecture"},
            {"id": 2, "title": "Domain-Driven Design"},
        ]
    }

    comments_payload = {
        "comments": [
            {"id": 1, "book_id": 1, "content": "Excellent read."},
            {"id": 2, "book_id": 1, "content": "Very practical."},
        ]
    }

    comments_payload_book_2_with_duplicate_ids = {
        "comments": [
            {"id": 1, "book_id": 999, "content": "Second book comment A"},
            {"id": 2, "book_id": 999, "content": "Second book comment B"},
        ]
    }

    comments_payload_book_999 = {
        "comments": [
            {"id": 1, "book_id": 0, "content": "Book 999 comment A"},
            {"id": 2, "book_id": 0, "content": "Book 999 comment B"},
        ]
    }

    book_999_payload = {"id": 999, "title": "Generated Book 999"}

    books_999_attempts = {"count": 0}

    async def fake_ai(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
        if path == "/books":
            return books_payload
        if path == "/books/1/comments":
            return comments_payload
        if path == "/books/6":
            return {"id": 6, "title": "Generated Book 6"}
        if path == "/books/2/comments":
            return comments_payload_book_2_with_duplicate_ids
        if path == "/books/999":
            books_999_attempts["count"] += 1
            if books_999_attempts["count"] == 1:
                return {
                    "error": "Not Found",
                    "message": "Book with ID '999' not found.",
                    "status": 404,
                }
            return book_999_payload
        if path == "/books/999/comments":
            return comments_payload_book_999
        if path == "/articles/2002":
            return {
                "id": 2,
                "articles": [
                    {
                        "id": 2,
                        "title": "An insightful read that captivates the imagination.",
                        "author": "Alice Johnson",
                    },
                    {
                        "id": 2,
                        "title": "I found the characters to be incredibly relatable.",
                        "author": "Mark Smith",
                    },
                ],
            }
        return {"error": "unexpected test path", "path": path}

    ai_mock = AsyncMock(side_effect=fake_ai)
    main.ai_client.get_ai_content = ai_mock

    return {
        "client": main.app.test_client(),
        "ai_mock": ai_mock,
        "books_payload": books_payload,
        "comments_payload": comments_payload,
        "comments_payload_book_2_with_duplicate_ids": comments_payload_book_2_with_duplicate_ids,
        "book_999_payload": book_999_payload,
        "comments_payload_book_999": comments_payload_book_999,
    }


@pytest.fixture(scope="session")
def ordered_test_env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test_simulator.db"
    return _build_test_env(db_path)


@pytest.fixture(scope="function")
def isolated_test_env(tmp_path):
    db_path = tmp_path / "isolated_test_simulator.db"
    return _build_test_env(db_path)
