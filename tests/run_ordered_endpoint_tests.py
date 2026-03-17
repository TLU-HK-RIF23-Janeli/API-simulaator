import subprocess
import sys


TEST_FILES = [
    "tests/test_01_books_cache.py",
    "tests/test_02_books_1_comments_cache.py",
    "tests/test_03_books_2_comments_rewrite_cache.py",
    "tests/test_04_books_1_single_cache_hit.py",
    "tests/test_05_comments_1_first_hit_no_ai.py",
    "tests/test_06_books_2_comments_1_not_found.py",
    "tests/test_07_books_999_comments_autogenerates_parent.py",
    "tests/test_08_books_1001_comments_parent_generation_fails.py",
    "tests/test_09_books_1111_comments_2_normalized_item_shape.py",
    "tests/test_10_unknown_items_generate_when_not_blacklisted.py",
    "tests/test_11_cache_table_shape_consistency.py",
    "tests/test_12_schema_mismatch_rejected.py",
    "tests/test_13_collection_refresh_after_new_item.py",
    "tests/test_14_delete_collection_forbidden.py",
    "tests/test_15_delete_nested_collection_forbidden.py",
    "tests/test_16_delete_item_and_verify_blocked.py",
    "tests/test_17_deleted_comment_absent_from_collections.py",
    "tests/test_18_delete_book_blocks_children.py",
    "tests/test_19_delete_nonexistent_and_double_delete.py",
]


def main():
    cmd = [sys.executable, "-m", "pytest", "-s", "-q", *TEST_FILES]
    print("Running ordered endpoint tests:")
    for test_file in TEST_FILES:
        print(f"- {test_file}")
    print()
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
