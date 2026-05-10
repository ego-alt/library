import os

from library.models import Book, db

# --- index / load_more ----------------------------------------------------------


def test_index_renders_with_no_books(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Library" in r.data


def test_load_more_returns_book_list(client, book):
    r = client.get("/load_more/0")
    assert r.status_code == 200
    items = r.get_json()
    assert len(items) == 1
    assert items[0]["filename"] == book.filename
    assert items[0]["cover"] == f"/cover/{book.filename}"


def test_load_more_filters_by_title(client, book):
    r = client.get("/load_more/0?title=Test")
    assert len(r.get_json()) == 1
    r = client.get("/load_more/0?title=Nonexistent")
    assert r.get_json() == []


# --- view=mine vs view=all ------------------------------------------------------


def test_view_all_returns_unstarted_books(client, book):
    """The default view returns books regardless of reading status."""
    r = client.get("/load_more/0?view=all")
    assert len(r.get_json()) == 1


def test_view_mine_excludes_unstarted_books(standard_client, book):
    """A logged-in user with no started books gets nothing in 'my' view."""
    r = standard_client.get("/load_more/0?view=mine")
    assert r.get_json() == []


def test_view_mine_includes_in_progress_books(standard_client, book):
    from library.choices import BookProgressChoice
    from library.models import Bookmark, db

    # Mark the book as started
    bm = Bookmark(
        user_id=2 if False else 1,  # standard_user is the only user, id=1
        book_id=book.id,
        status=BookProgressChoice.IN_PROGRESS,
    )
    db.session.add(bm)
    db.session.commit()

    r = standard_client.get("/load_more/0?view=mine")
    items = r.get_json()
    assert len(items) == 1
    assert items[0]["filename"] == book.filename


def test_view_mine_falls_back_to_all_for_anonymous(client, book):
    # Anonymous users have no library; the route degrades to 'all'
    r = client.get("/load_more/0?view=mine")
    assert len(r.get_json()) == 1


def test_view_all_orders_by_created_at_desc(standard_client, app, book_dir):
    """A newly-added unread book should appear before a previously-read one
    in the default 'all' view."""
    import time

    from library.choices import BookProgressChoice
    from library.models import Book, Bookmark, db
    from tests._epub_builder import build_epub3

    # Older book that the user has been reading
    old_path = book_dir / "old.epub"
    old_path.write_bytes(build_epub3(title="Old", author="Author"))
    old = Book(title="Old", author="Author", filename="old.epub",
               cover_path="OEBPS/cover.png", access_level="standard")
    db.session.add(old)
    db.session.commit()
    db.session.add(Bookmark(user_id=1, book_id=old.id,
                            status=BookProgressChoice.IN_PROGRESS))
    db.session.commit()

    # Newer book the user hasn't touched
    time.sleep(0.01)
    new_path = book_dir / "new.epub"
    new_path.write_bytes(build_epub3(title="New", author="Author"))
    new = Book(title="New", author="Author", filename="new.epub",
               cover_path="OEBPS/cover.png", access_level="standard")
    db.session.add(new)
    db.session.commit()

    r = standard_client.get("/load_more/0?view=all")
    filenames = [item["filename"] for item in r.get_json()]
    # Newest first regardless of reading activity
    assert filenames.index("new.epub") < filenames.index("old.epub")


def test_view_mine_orders_by_last_read_desc(standard_client, app, book_dir):
    """My-books view should put the most-recently-opened book first."""
    from datetime import datetime, timedelta, timezone

    from library.choices import BookProgressChoice
    from library.models import Book, Bookmark, db
    from tests._epub_builder import build_epub3

    a_path = book_dir / "a.epub"
    a_path.write_bytes(build_epub3(title="A", author="A"))
    a = Book(title="A", author="A", filename="a.epub",
             cover_path="OEBPS/cover.png", access_level="standard")
    b_path = book_dir / "b.epub"
    b_path.write_bytes(build_epub3(title="B", author="B"))
    b = Book(title="B", author="B", filename="b.epub",
             cover_path="OEBPS/cover.png", access_level="standard")
    db.session.add_all([a, b])
    db.session.commit()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(Bookmark(user_id=1, book_id=a.id,
                            status=BookProgressChoice.IN_PROGRESS,
                            last_read=now - timedelta(days=2)))
    db.session.add(Bookmark(user_id=1, book_id=b.id,
                            status=BookProgressChoice.IN_PROGRESS,
                            last_read=now))
    db.session.commit()

    r = standard_client.get("/load_more/0?view=mine")
    filenames = [item["filename"] for item in r.get_json()]
    assert filenames[0] == "b.epub"
    assert filenames[1] == "a.epub"


# --- /cover ---------------------------------------------------------------------


def test_cover_serves_png_with_long_cache(client, book):
    r = client.get(f"/cover/{book.filename}")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert "max-age=31536000" in r.headers["Cache-Control"]
    assert r.headers.get("ETag")
    assert r.data.startswith(b"\x89PNG")


def test_cover_returns_304_on_matching_etag(client, book):
    r1 = client.get(f"/cover/{book.filename}")
    etag = r1.headers["ETag"]
    r2 = client.get(f"/cover/{book.filename}", headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_cover_404s_for_unknown_book(client):
    r = client.get("/cover/nope.epub")
    assert r.status_code == 404


# --- /download ------------------------------------------------------------------


def test_download_serves_epub_for_standard_access(client, book):
    r = client.get(f"/download/{book.filename}")
    assert r.status_code == 200
    assert r.data[:4] == b"PK\x03\x04"  # ZIP signature


def test_download_blocks_anonymous_for_restricted(client, book):
    book.access_level = "restricted"
    db.session.commit()
    r = client.get(f"/download/{book.filename}")
    assert r.status_code == 403


def test_download_allows_admin_for_restricted(admin_client, book):
    book.access_level = "restricted"
    db.session.commit()
    r = admin_client.get(f"/download/{book.filename}")
    assert r.status_code == 200


# --- DELETE /book ---------------------------------------------------------------


def test_delete_book_removes_db_row_and_file(admin_client, app, book):
    epub_path = os.path.join(app.config["BOOK_DIR"], book.filename)
    assert os.path.exists(epub_path)
    fn = book.filename

    r = admin_client.delete(f"/book/{fn}")
    assert r.status_code == 200

    assert not os.path.exists(epub_path)
    assert Book.query.filter_by(filename=fn).first() is None


def test_delete_book_succeeds_even_when_file_missing(admin_client, app, book):
    os.remove(os.path.join(app.config["BOOK_DIR"], book.filename))
    fn = book.filename

    r = admin_client.delete(f"/book/{fn}")
    assert r.status_code == 200
    assert Book.query.filter_by(filename=fn).first() is None


def test_delete_unknown_book_returns_404(admin_client):
    r = admin_client.delete("/book/nope.epub")
    assert r.status_code == 404
