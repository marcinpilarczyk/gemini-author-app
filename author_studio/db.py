from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class AuthorStudioDB:
    def __init__(self, path: str | Path = "author_studio.db") -> None:
        self.path = str(path)
        self.init()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT 'Untitled Book',
                    concept TEXT NOT NULL DEFAULT '',
                    outline TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    chapter_num INTEGER NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    UNIQUE(book_id, chapter_num),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
                """
            )

    def list_books(self):
        with self.connection() as conn:
            return conn.execute("SELECT id, title FROM books ORDER BY id").fetchall()

    def create_book(self, title: str) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO books (title, concept, outline) VALUES (?, '', '')",
                (title.strip() or "Untitled Book",),
            )
            return int(cursor.lastrowid)

    def get_book(self, book_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()

    def update_book(self, book_id: int, title: str, concept: str, outline: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE books SET title = ?, concept = ?, outline = ? WHERE id = ?",
                (title.strip() or "Untitled Book", concept, outline, book_id),
            )

    def list_chapters(self, book_id: int):
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_num",
                (book_id,),
            ).fetchall()

    def save_chapter(self, book_id: int, number: int, content: str, summary: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO chapters (book_id, chapter_num, content, summary)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id, chapter_num)
                DO UPDATE SET content = excluded.content,
                              summary = CASE
                                  WHEN excluded.summary <> '' THEN excluded.summary
                                  ELSE chapters.summary
                              END
                """,
                (book_id, number, content, summary),
            )

    def delete_chapter(self, book_id: int, number: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM chapters WHERE book_id = ? AND chapter_num = ?",
                (book_id, number),
            )

    def replace_chapters(self, book_id: int, chapters: list[tuple[int, str]]) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            conn.executemany(
                "INSERT INTO chapters (book_id, chapter_num, content, summary) VALUES (?, ?, ?, '')",
                [(book_id, number, content) for number, content in chapters],
            )
