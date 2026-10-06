from author_studio.db import AuthorStudioDB


def test_book_and_chapter_round_trip(tmp_path):
    db = AuthorStudioDB(tmp_path / "studio.db")
    book_id = db.create_book("Test Book")
    db.update_book(book_id, "Test Book", "Concept", "Outline")
    db.save_chapter(book_id, 1, "Chapter text", "Summary")

    book = db.get_book(book_id)
    chapters = db.list_chapters(book_id)

    assert book["concept"] == "Concept"
    assert len(chapters) == 1
    assert chapters[0]["summary"] == "Summary"


def test_replace_chapters(tmp_path):
    db = AuthorStudioDB(tmp_path / "studio.db")
    book_id = db.create_book("Test Book")
    db.save_chapter(book_id, 1, "Old")
    db.replace_chapters(book_id, [(1, "New one"), (2, "New two")])

    chapters = db.list_chapters(book_id)
    assert [row["content"] for row in chapters] == ["New one", "New two"]
