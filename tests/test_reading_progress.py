"""Books you're reading: the library opens on them, and their covers show how
far in you are."""

from datetime import datetime, timedelta

from library.choices import BookProgressChoice
from library.models import Book, Bookmark, db
from tests._epub_builder import build_epub3


def _add_book(book_dir, filename, title, access_level="standard"):
    (book_dir / filename).write_bytes(build_epub3(title=title))
    book = Book(title=title, author="A. Author", filename=filename, access_level=access_level)
    db.session.add(book)
    db.session.commit()
    return book


def _bookmark(user, book, status, minutes_ago=0, chapter=0, position=0.0):
    db.session.add(
        Bookmark(
            user_id=user.id,
            book_id=book.id,
            status=status,
            chapter_index=chapter,
            position=position,
            last_read=datetime.utcnow() - timedelta(minutes=minutes_ago),
        )
    )
    db.session.commit()


def _view(html):
    return html.split('window.initialView = "')[1].split('"')[0]


def test_opens_on_reading_when_something_is_in_progress(standard_client, standard_user, book_dir):
    older = _add_book(book_dir, "older.epub", "Older Book")
    newer = _add_book(book_dir, "newer.epub", "Newer Book")
    _add_book(book_dir, "unread.epub", "Unread Book")
    _bookmark(standard_user, older, BookProgressChoice.IN_PROGRESS, minutes_ago=60)
    _bookmark(standard_user, newer, BookProgressChoice.IN_PROGRESS, minutes_ago=1)

    html = standard_client.get("/").data.decode()
    assert _view(html) == "reading"
    assert html.index("Newer Book") < html.index("Older Book")
    assert "Unread Book" not in html


def test_opens_on_everything_otherwise(standard_client, standard_user, book_dir):
    done = _add_book(book_dir, "done.epub", "Finished Book")
    _bookmark(standard_user, done, BookProgressChoice.FINISHED)
    assert _view(standard_client.get("/").data.decode()) == "all"


def test_view_param_still_wins(standard_client, standard_user, book_dir):
    b = _add_book(book_dir, "b.epub", "Some Book")
    _bookmark(standard_user, b, BookProgressChoice.IN_PROGRESS)
    assert _view(standard_client.get("/?view=all").data.decode()) == "all"


def test_anonymous_opens_on_everything(client, book):
    assert _view(client.get("/").data.decode()) == "all"


def test_covers_carry_whole_book_progress_only_while_reading(standard_client, standard_user, book_dir):
    reading = _add_book(book_dir, "p.epub", "Progress Book")
    done = _add_book(book_dir, "d.epub", "Done Book")
    # Halfway through the last of two equal-ish chapters → past halfway.
    _bookmark(standard_user, reading, BookProgressChoice.IN_PROGRESS, chapter=1, position=0.5)
    _bookmark(standard_user, done, BookProgressChoice.FINISHED, chapter=1, position=1.0)

    books = standard_client.get("/load_more/0?view=all").get_json()
    rows = {b["title"]: b for b in books}
    assert 0.5 < rows["Progress Book"]["progress"] < 1.0
    assert rows["Done Book"]["progress"] is None

    html = standard_client.get("/?view=all").data.decode()
    pct = int(rows["Progress Book"]["progress"] * 100)
    assert f"A. Author · {pct}%" in html


def test_reading_hides_trashed_and_restricted_books(standard_client, standard_user, book_dir):
    trashed = _add_book(book_dir, "t.epub", "Trashed Book")
    trashed.deleted_at = datetime.utcnow()
    secret = _add_book(book_dir, "s.epub", "Secret Book", access_level="restricted")
    db.session.commit()
    _bookmark(standard_user, trashed, BookProgressChoice.IN_PROGRESS)
    _bookmark(standard_user, secret, BookProgressChoice.IN_PROGRESS)

    html = standard_client.get("/").data.decode()
    assert _view(html) == "all"  # nothing visible is in progress
    assert "Trashed Book" not in html
    assert "Secret Book" not in html
