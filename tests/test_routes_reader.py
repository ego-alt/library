import json

from library.choices import BookProgressChoice
from library.models import Bookmark


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


def test_load_book_creates_bookmark_for_logged_in_user(standard_client, book, standard_user):
    standard_client.get(f"/load_book/{book.filename}")
    bm = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).first()
    assert bm is not None
    # Opening a book transitions UNREAD -> IN_PROGRESS
    assert bm.status == BookProgressChoice.IN_PROGRESS


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


def test_bookmark_anonymous_returns_200_with_message(client, book):
    # Anonymous users shouldn't crash; the route returns a soft 200 message
    r = client.post(f"/bookmark/{book.filename}", json={})
    assert r.status_code == 200
    assert "Authentication" in r.get_json()["message"]


# --- /tag_finished --------------------------------------------------------------


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
