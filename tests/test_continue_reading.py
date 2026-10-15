"""The "Continue reading" row on the library page."""

from datetime import datetime, timedelta

from library.choices import BookProgressChoice
from library.models import Book, Bookmark, db
from tests._epub_builder import build_epub3


def _add_book(book_dir, filename, title, access_level="standard"):
    (book_dir / filename).write_bytes(build_epub3(title=title))
    book = Book(title=title, author="A. Author", filename=filename,
                access_level=access_level)
    db.session.add(book)
    db.session.commit()
    return book


def _bookmark(user, book, status, minutes_ago=0, chapter=0, position=0.0):
    db.session.add(Bookmark(
        user_id=user.id, book_id=book.id, status=status,
        chapter_index=chapter, position=position,
        last_read=datetime.utcnow() - timedelta(minutes=minutes_ago),
    ))
    db.session.commit()


def test_anonymous_sees_no_continue_row(client, book):
    assert b"continue-reading" not in client.get("/").data


def test_row_lists_in_progress_books_most_recent_first(
    standard_client, standard_user, book_dir
):
    older = _add_book(book_dir, "older.epub", "Older Book")
    newer = _add_book(book_dir, "newer.epub", "Newer Book")
    done = _add_book(book_dir, "done.epub", "Finished Book")
    _bookmark(standard_user, older, BookProgressChoice.IN_PROGRESS, minutes_ago=60)
    _bookmark(standard_user, newer, BookProgressChoice.IN_PROGRESS, minutes_ago=1)
    _bookmark(standard_user, done, BookProgressChoice.FINISHED)

    html = standard_client.get("/").data.decode()
    assert 'class="continue-reading"' in html
    assert html.index("Newer Book") < html.index("Older Book")
    assert "Finished Book" not in html.split('class="library')[0]


def test_row_caps_at_three_books(standard_client, standard_user, book_dir):
    for i in range(5):
        b = _add_book(book_dir, f"b{i}.epub", f"Book {i}")
        _bookmark(standard_user, b, BookProgressChoice.IN_PROGRESS, minutes_ago=i)

    from library.routes.index import continue_reading

    with standard_client:
        standard_client.get("/")
        assert [b["title"] for b in continue_reading()] == ["Book 0", "Book 1", "Book 2"]


def test_row_reports_whole_book_progress(standard_client, standard_user, book_dir):
    b = _add_book(book_dir, "p.epub", "Progress Book")
    # Halfway through the last of two equal-ish chapters → past halfway.
    _bookmark(standard_user, b, BookProgressChoice.IN_PROGRESS, chapter=1, position=0.5)

    from library.routes.index import continue_reading

    with standard_client:
        standard_client.get("/")
        (row,) = continue_reading()
    assert 0.5 < row["progress"] < 1.0
    assert row["cover"].startswith("/cover/p.epub?v=")


def test_row_hides_trashed_and_restricted_books(
    standard_client, standard_user, book_dir
):
    trashed = _add_book(book_dir, "t.epub", "Trashed Book")
    trashed.deleted_at = datetime.utcnow()
    secret = _add_book(book_dir, "s.epub", "Secret Book", access_level="restricted")
    db.session.commit()
    _bookmark(standard_user, trashed, BookProgressChoice.IN_PROGRESS)
    _bookmark(standard_user, secret, BookProgressChoice.IN_PROGRESS)

    html = standard_client.get("/").data.decode()
    assert "Trashed Book" not in html
    assert "Secret Book" not in html
