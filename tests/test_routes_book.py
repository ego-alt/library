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
