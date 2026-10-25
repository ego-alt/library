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
    # Versioned by file mtime so a changed cover gets a new URL.
    assert items[0]["cover"].startswith(f"/cover/{book.filename}?v=")
    assert items[0]["access_level"] == "standard"


def test_load_more_excludes_restricted_for_standard_user(standard_client, book):
    book.access_level = "restricted"
    db.session.commit()
    r = standard_client.get("/load_more/0")
    assert r.get_json() == []
    assert r.headers["X-Total-Count"] == "0"


def test_load_more_excludes_restricted_for_anonymous(client, book):
    book.access_level = "restricted"
    db.session.commit()
    assert client.get("/load_more/0").get_json() == []


def test_load_more_includes_restricted_for_admin(admin_client, book):
    book.access_level = "restricted"
    db.session.commit()
    items = admin_client.get("/load_more/0").get_json()
    assert len(items) == 1
    assert items[0]["access_level"] == "restricted"


def test_load_more_searches_with_q(client, book):
    r = client.get("/load_more/0?q=Test")
    assert len(r.get_json()) == 1
    r = client.get("/load_more/0?q=Nonexistent")
    assert r.get_json() == []


def test_load_more_includes_total_count_header(client, book):
    """Frontend uses X-Total-Count to cap how many skeletons to show."""
    r = client.get("/load_more/0")
    assert r.headers["X-Total-Count"] == "1"
    r = client.get("/load_more/0?q=Nonexistent")
    assert r.headers["X-Total-Count"] == "0"


def test_index_template_exposes_total_books(client, book):
    """Server-rendered initial total_books seeds window.totalBooks."""
    r = client.get("/")
    assert b"window.totalBooks = 1" in r.data


# --- reading-status views ---------------------------------------------------------


def test_view_all_returns_unstarted_books(client, book):
    """The default view returns books regardless of reading status."""
    r = client.get("/load_more/0?view=all")
    assert len(r.get_json()) == 1


def test_view_reading_excludes_unstarted_books(standard_client, book):
    """A logged-in user with no started books gets nothing in 'reading'."""
    r = standard_client.get("/load_more/0?view=reading")
    assert r.get_json() == []


def test_view_reading_includes_in_progress_books(standard_client, book):
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

    r = standard_client.get("/load_more/0?view=reading")
    items = r.get_json()
    assert len(items) == 1
    assert items[0]["filename"] == book.filename


def test_unknown_view_falls_back_to_all(client, book):
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

    r = standard_client.get("/load_more/0?view=reading")
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


def test_cover_bytes_are_memoized_across_requests(client, book, mocker):
    """Repeat fetches without a matching ETag should hit the in-memory cache,
    not re-extract from the zip."""
    import library.routes.index as index_module
    spy = mocker.spy(index_module, "read_epub_cover")

    r1 = client.get(f"/cover/{book.filename}")
    r2 = client.get(f"/cover/{book.filename}")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.data == r2.data
    # Only one zip extraction across two requests.
    assert spy.call_count == 1


def test_cover_cache_invalidates_when_file_mtime_changes(client, book, app, mocker):
    """If the EPUB on disk is updated (e.g. via /update_cover), a fresh request
    should re-extract because the mtime changed -> new cache key."""
    import os
    import time

    import library.routes.index as index_module
    spy = mocker.spy(index_module, "read_epub_cover")

    client.get(f"/cover/{book.filename}")

    # Bump mtime to simulate a cover-update
    epub_path = os.path.join(app.config["BOOK_DIR"], book.filename)
    new_mtime = int(time.time()) + 5
    os.utime(epub_path, (new_mtime, new_mtime))

    client.get(f"/cover/{book.filename}")
    assert spy.call_count == 2


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


def test_delete_book_moves_it_to_trash(admin_client, app, book):
    """Delete is undoable: the row is flagged and the EPUB stays on disk."""
    epub_path = os.path.join(app.config["BOOK_DIR"], book.filename)
    fn = book.filename

    r = admin_client.delete(f"/book/{fn}")
    assert r.status_code == 200
    assert r.get_json()["title"] == "Test Book"

    assert os.path.exists(epub_path)
    assert Book.query.filter_by(filename=fn).one().deleted_at is not None


def test_deleted_book_is_hidden_everywhere(admin_client, book):
    fn = book.filename
    admin_client.delete(f"/book/{fn}")

    assert admin_client.get("/load_more/0").get_json() == []
    assert admin_client.get("/load_more/0").headers["X-Total-Count"] == "0"
    assert admin_client.get(f"/read/{fn}").status_code == 404
    assert admin_client.get(f"/book_metadata/{fn}").status_code == 404
    assert admin_client.get(f"/download/{fn}").status_code == 404
    assert admin_client.get("/books?title=Test%20Book").get_json()["matches"] == []
    # Deleting again is a 404, not a second trash entry.
    assert admin_client.delete(f"/book/{fn}").status_code == 404


def test_restore_undoes_delete(admin_client, book):
    fn = book.filename
    admin_client.delete(f"/book/{fn}")

    r = admin_client.post(f"/book/{fn}/restore")
    assert r.status_code == 200
    assert Book.query.filter_by(filename=fn).one().deleted_at is None
    assert len(admin_client.get("/load_more/0").get_json()) == 1


def test_restore_requires_admin(standard_client, book):
    assert standard_client.post(f"/book/{book.filename}/restore").status_code == 403


def test_purge_trash_removes_only_expired_books(app, book, book_dir):
    from datetime import datetime, timedelta

    from library.routes.index import purge_trash

    epub_path = os.path.join(app.config["BOOK_DIR"], book.filename)
    book.deleted_at = datetime.utcnow() - timedelta(days=5)
    db.session.commit()
    assert purge_trash(retention_days=30) == 0
    assert os.path.exists(epub_path)

    book.deleted_at = datetime.utcnow() - timedelta(days=31)
    db.session.commit()
    assert purge_trash(retention_days=30) == 1
    assert not os.path.exists(epub_path)
    assert Book.query.count() == 0


def test_purge_trash_succeeds_even_when_file_missing(app, book):
    from datetime import datetime, timedelta

    from library.routes.index import purge_trash

    os.remove(os.path.join(app.config["BOOK_DIR"], book.filename))
    book.deleted_at = datetime.utcnow() - timedelta(days=31)
    db.session.commit()
    assert purge_trash(retention_days=30) == 1
    assert Book.query.count() == 0


def test_delete_unknown_book_returns_404(admin_client):
    r = admin_client.delete("/book/nope.epub")
    assert r.status_code == 404


# --- GET /books (book-scanner title+author lookup) ------------------------------


def test_books_search_requires_auth(client, book):
    r = client.get("/books?title=Test%20Book")
    assert r.status_code == 401


def test_books_search_finds_owned_book(standard_client, book):
    r = standard_client.get("/books?title=Test%20Book&author=Test%20Author")
    assert r.status_code == 200
    matches = r.get_json()["matches"]
    assert len(matches) == 1
    assert matches[0]["filename"] == book.filename
    assert matches[0]["score"] >= 0.99


def test_books_search_tolerates_fuzzy_title(standard_client, book):
    """A slightly-off scanned title still resolves to the owned book."""
    r = standard_client.get("/books?title=The%20Test%20Book&author=Test%20Author")
    matches = r.get_json()["matches"]
    assert matches and matches[0]["filename"] == book.filename


def test_books_search_returns_empty_for_unrelated(standard_client, book):
    r = standard_client.get("/books?title=War%20and%20Peace&author=Tolstoy")
    assert r.get_json()["matches"] == []


def test_books_search_requires_a_query(standard_client):
    r = standard_client.get("/books")
    assert r.status_code == 400


def test_books_search_excludes_restricted_for_standard_user(standard_client, book):
    book.access_level = "restricted"
    db.session.commit()
    r = standard_client.get("/books?title=Test%20Book&author=Test%20Author")
    assert r.get_json()["matches"] == []


# --- cover thumbnails + fallback cover ---------------------------------------------


def _real_png(width=800, height=1200):
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (width, height), (52, 73, 94)).save(out, "PNG")
    return out.getvalue()


def test_cover_thumbnail_is_small_webp(client, app, book):
    from library.utils import update_epub_cover

    update_epub_cover(os.path.join(app.config["BOOK_DIR"], book.filename), _real_png())
    full = client.get(f"/cover/{book.filename}")
    thumb = client.get(f"/cover/{book.filename}?w=400")
    assert thumb.status_code == 200
    assert thumb.headers["Content-Type"] == "image/webp"
    assert thumb.data[:4] == b"RIFF" and thumb.data[8:12] == b"WEBP"
    assert full.headers["ETag"] != thumb.headers["ETag"]
    assert len(thumb.data) < len(full.data)


def test_undecodable_cover_thumbnail_serves_original(client, book):
    """The test EPUB's tiny PNG is truncated; thumbnails fall back gracefully."""
    r = client.get(f"/cover/{book.filename}?w=400")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"


def test_cover_thumbnail_widths_snap(client, book):
    a = client.get(f"/cover/{book.filename}?w=90")
    b = client.get(f"/cover/{book.filename}?w=400")
    assert a.headers["ETag"] == b.headers["ETag"]


def test_load_more_uses_thumbnail_urls(client, book):
    cover = client.get("/load_more/0").get_json()[0]["cover"]
    assert "w=400" in cover and "v=" in cover


def test_book_without_cover_gets_typographic_fallback(client, app, book_dir):
    from library.models import Book, db
    from tests._epub_builder import build_epub3

    (book_dir / "bare.epub").write_bytes(build_epub3(include_cover=False))
    db.session.add(Book(title="A Very Long Title Without Any Cover At All",
                        author="Someone & Co", filename="bare.epub"))
    db.session.commit()

    r = client.get("/cover/bare.epub")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/svg+xml"
    assert b"Someone &amp; Co" in r.data
    # Thumbnails of the fallback stay SVG (vector, already tiny).
    assert client.get("/cover/bare.epub?w=400").headers["Content-Type"] == "image/svg+xml"


# --- status views + search ----------------------------------------------------------


def _status(user, book, status):
    from library.models import Bookmark

    db.session.add(Bookmark(user_id=user.id, book_id=book.id, status=status))
    db.session.commit()


def _second_book(book_dir, title="Other Book", author="Someone Else"):
    from tests._epub_builder import build_epub3

    (book_dir / "other.epub").write_bytes(build_epub3(title=title))
    b = Book(title=title, author=author, filename="other.epub")
    db.session.add(b)
    db.session.commit()
    return b


def test_status_views(standard_client, standard_user, book, book_dir):
    from library.choices import BookProgressChoice

    other = _second_book(book_dir)
    _status(standard_user, book, BookProgressChoice.FINISHED)

    names = lambda view: [b["filename"] for b in standard_client.get(f"/load_more/0?view={view}").get_json()]  # noqa: E731
    assert names("finished") == [book.filename]
    assert names("reading") == []
    assert names("unread") == [other.filename]
    assert sorted(names("all")) == sorted([book.filename, other.filename])


def test_status_views_fall_back_to_all_when_signed_out(client, book):
    assert len(client.get("/load_more/0?view=finished").get_json()) == 1


def test_search_matches_title_author_and_tags(standard_client, book, book_dir):
    _second_book(book_dir, title="Postwar", author="Tony Judt")
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "tags": ["bedside"]},
    )
    q = lambda text: [b["filename"] for b in standard_client.get(f"/load_more/0?q={text}").get_json()]  # noqa: E731
    assert q("judt") == ["other.epub"]
    assert q("bedside") == [book.filename]
    assert q("tony postwar") == ["other.epub"]
    assert q("tony bedside") == []


def test_book_with_several_tags_is_listed_once(standard_client, book):
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "tags": ["a", "b", "c"]},
    )
    r = standard_client.get("/load_more/0")
    assert len(r.get_json()) == 1
    assert r.headers["X-Total-Count"] == "1"


def test_load_more_pages_through_a_large_library(client, app, book_dir):
    from library.routes.index import BOOKS_PER_LOAD
    from tests._epub_builder import build_epub3

    epub = build_epub3()
    for i in range(BOOKS_PER_LOAD + 6):
        (book_dir / f"b{i:02}.epub").write_bytes(epub)
        db.session.add(Book(title=f"Book {i:02}", author="A", filename=f"b{i:02}.epub"))
    db.session.commit()

    first = client.get("/load_more/0").get_json()
    second = client.get(f"/load_more/{len(first)}").get_json()
    assert len(first) == BOOKS_PER_LOAD
    assert len(second) == 6
    assert not {b["filename"] for b in first} & {b["filename"] for b in second}


def test_update_cover_adds_a_cover_to_a_book_without(standard_client, app, book_dir):
    import io

    from library.models import Book, db
    from library.utils import read_epub_cover
    from tests._epub_builder import build_epub3

    (book_dir / "bare.epub").write_bytes(build_epub3(include_cover=False))
    db.session.add(Book(title="Bare", author="A", filename="bare.epub", cover_path=None, access_level="standard"))
    db.session.commit()
    jpeg = b"\xff\xd8\xff\xe0UPLOADED"
    r = standard_client.post(
        "/update_cover",
        data={"filename": "bare.epub", "cover": (io.BytesIO(jpeg), "c.jpg")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    book = Book.query.filter_by(filename="bare.epub").one()
    assert book.cover_path == "OEBPS/library-cover.jpg"
    assert read_epub_cover(str(book_dir / "bare.epub"), book.cover_path) == jpeg
