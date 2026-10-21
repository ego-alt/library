import io
import json

import pytest

from library.choices import BookProgressChoice
from library.models import Bookmark, db


def _read_ndjson(response):
    text = response.get_data(as_text=True)
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def test_load_book_streams_metadata_then_chapters(client, book):
    r = client.get(f"/load_book/{book.filename}")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/x-ndjson")
    events = _read_ndjson(r)

    # First event is metadata
    meta = events[0]
    assert meta["type"] == "metadata"
    assert meta["title"] == "Test Book"
    assert meta["spine_length"] >= 2
    assert isinstance(meta["toc"], list)

    # Subsequent events are chapter payloads, one per spine item
    chapter_events = [e for e in events[1:] if e["type"] == "chapter"]
    assert len(chapter_events) == meta["spine_length"]
    for ch in chapter_events:
        assert "content" in ch
        assert "index" in ch


def test_opening_a_book_does_not_mark_it_started(standard_client, book, standard_user):
    """Peeking at a book shouldn't put it in "Reading"."""
    standard_client.get(f"/load_book/{book.filename}")
    assert Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).first() is None


def test_saving_the_opening_position_does_not_mark_started(standard_client, book, standard_user):
    standard_client.post(f"/bookmark/{book.filename}", json={"chapter_index": 0, "position": 0})
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).one()
    assert bm.status == BookProgressChoice.UNREAD


def test_load_book_404_for_unknown_book(client):
    r = client.get("/load_book/missing.epub")
    assert r.status_code == 404


# --- /bookmark ------------------------------------------------------------------


def test_bookmark_post_creates_and_persists(standard_client, book, standard_user):
    r = standard_client.post(
        f"/bookmark/{book.filename}",
        json={"chapter_index": 3, "position": 0.42},
    )
    assert r.status_code == 200
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).first()
    assert bm.chapter_index == 3
    assert bm.position == 0.42


def test_bookmark_post_updates_existing(standard_client, book, standard_user):
    standard_client.post(
        f"/bookmark/{book.filename}", json={"chapter_index": 1, "position": 0.1}
    )
    standard_client.post(
        f"/bookmark/{book.filename}", json={"chapter_index": 5, "position": 0.9}
    )
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).first()
    assert bm.chapter_index == 5
    assert bm.position == 0.9


def test_bookmark_get_returns_zero_when_missing(standard_client, book):
    r = standard_client.get(f"/bookmark/{book.filename}")
    assert r.status_code == 200
    assert r.get_json() == {"chapter_index": 0, "position": 0}


def test_bookmark_anonymous_returns_401(client, book):
    r = client.get(f"/bookmark/{book.filename}")
    assert r.status_code == 401
    assert "Sign in" in r.get_json()["error"]

def test_tag_finished_marks_bookmark(standard_client, book, standard_user):
    r = standard_client.post(f"/tag_finished/{book.filename}")
    assert r.status_code == 200
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).first()
    assert bm.status == BookProgressChoice.FINISHED


def test_tag_finished_requires_auth(client, book):
    r = client.post(f"/tag_finished/{book.filename}")
    assert r.status_code == 401


# --- /book_asset ----------------------------------------------------------------


def test_book_asset_serves_cover_with_etag(client, book):
    r = client.get(f"/book_asset/{book.filename}/OEBPS/cover.png")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert r.data.startswith(b"\x89PNG")
    assert r.headers.get("ETag")


def test_book_asset_returns_304_on_matching_etag(client, book):
    r1 = client.get(f"/book_asset/{book.filename}/OEBPS/cover.png")
    r2 = client.get(
        f"/book_asset/{book.filename}/OEBPS/cover.png",
        headers={"If-None-Match": r1.headers["ETag"]},
    )
    assert r2.status_code == 304


def test_book_asset_404s_for_missing_path_inside_zip(client, book):
    r = client.get(f"/book_asset/{book.filename}/OEBPS/missing.png")
    assert r.status_code == 404


# --- access control for restricted books ----------------------------------------


def _restrict(book):
    book.access_level = "restricted"
    db.session.commit()


def test_read_book_blocks_anonymous_for_restricted(client, book):
    _restrict(book)
    r = client.get(f"/read/{book.filename}")
    assert r.status_code == 403


def test_read_book_blocks_standard_for_restricted(standard_client, book):
    _restrict(book)
    r = standard_client.get(f"/read/{book.filename}")
    assert r.status_code == 403


def test_read_book_allows_admin_for_restricted(admin_client, book):
    _restrict(book)
    r = admin_client.get(f"/read/{book.filename}")
    assert r.status_code == 200


def test_load_book_blocks_standard_for_restricted(standard_client, book):
    _restrict(book)
    r = standard_client.get(f"/load_book/{book.filename}")
    assert r.status_code == 403


def test_load_book_allows_admin_for_restricted(admin_client, book):
    _restrict(book)
    r = admin_client.get(f"/load_book/{book.filename}")
    assert r.status_code == 200


def test_book_asset_blocks_standard_for_restricted(standard_client, book):
    _restrict(book)
    r = standard_client.get(f"/book_asset/{book.filename}/OEBPS/cover.png")
    assert r.status_code == 403


def test_book_asset_allows_admin_for_restricted(admin_client, book):
    _restrict(book)
    r = admin_client.get(f"/book_asset/{book.filename}/OEBPS/cover.png")
    assert r.status_code == 200


# --- whole-book progress + offline-friendly reader -------------------------------


def test_load_book_metadata_includes_chapter_sizes(client, book):
    import json

    first = client.get(f"/load_book/{book.filename}").data.split(b"\n")[0]
    meta = json.loads(first)
    assert len(meta["chapter_sizes"]) == meta["spine_length"]
    assert all(size > 0 for size in meta["chapter_sizes"])


def test_read_book_exposes_book_version(client, book):
    r = client.get(f"/read/{book.filename}")
    assert b"window.BOOK_VERSION" in r.data
    assert b"<title>Test Book</title>" in r.data


def test_bookmark_post_marks_unread_book_in_progress(
    standard_client, book, standard_user
):
    """The reader may open a book from its offline copy without hitting
    load_book, so saving a position must also mark the book as started."""
    from library.choices import BookProgressChoice
    from library.models import Bookmark

    standard_client.post(
        f"/bookmark/{book.filename}", json={"chapter_index": 1, "position": 0.5}
    )
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).one()
    assert bm.status == BookProgressChoice.IN_PROGRESS


def test_bookmark_post_keeps_finished_status(standard_client, book, standard_user):
    from library.choices import BookProgressChoice
    from library.models import Bookmark, db

    db.session.add(Bookmark(
        user_id=standard_user.id, book_id=book.id,
        status=BookProgressChoice.FINISHED,
    ))
    db.session.commit()
    standard_client.post(
        f"/bookmark/{book.filename}", json={"chapter_index": 0, "position": 0.1}
    )
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).one()
    assert bm.status == BookProgressChoice.FINISHED


def test_missing_book_page_is_html_for_browsers(client):
    r = client.get("/read/nope.epub", headers={"Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 404
    assert b"This book isn't in the library" in r.data


def test_missing_book_is_json_for_api_calls(client):
    r = client.get("/read/nope.epub", headers={"Accept": "*/*"})
    assert r.status_code == 404
    assert r.get_json() == {"error": "Book not found"}


# The per-book JSON endpoints hide restricted books from non-admins entirely
# (404, not 403), so a filename can't be probed for.
RESTRICTED_JSON_ENDPOINTS = [
    ("get", "/book_metadata/{f}"),
    ("post", "/book_metadata/{f}"),
    ("get", "/bookmark/{f}"),
    ("post", "/bookmark/{f}"),
    ("post", "/tag_finished/{f}"),
    ("get", "/cover/{f}"),
]


@pytest.mark.parametrize("method,path", RESTRICTED_JSON_ENDPOINTS)
def test_restricted_book_hidden_from_standard(standard_client, book, method, path):
    _restrict(book)
    r = getattr(standard_client, method)(path.format(f=book.filename), json={"tags": ["x"]})
    assert r.status_code == 404


@pytest.mark.parametrize("method,path", RESTRICTED_JSON_ENDPOINTS)
def test_restricted_book_open_to_admin(admin_client, book, method, path):
    _restrict(book)
    r = getattr(admin_client, method)(path.format(f=book.filename), json={"tags": ["x"]})
    assert r.status_code == 200


def test_restricted_cover_upload_hidden_from_standard(standard_client, book):
    _restrict(book)
    r = standard_client.post(
        "/update_cover",
        data={"filename": book.filename, "cover": (io.BytesIO(b"png"), "c.png")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 404
