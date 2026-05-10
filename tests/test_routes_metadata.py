from library.choices import BookProgressChoice
from library.models import Bookmark, Tag, db


def test_get_metadata_returns_book_fields(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["title"] == "Test Book"
    assert payload["author"] == "Test Author"
    assert payload["filename"] == book.filename
    assert payload["cover"] == f"/cover/{book.filename}"


def test_get_metadata_404_for_unknown_book(client):
    r = client.get("/book_metadata/missing.epub")
    assert r.status_code == 404


def test_post_metadata_requires_auth(client, book):
    r = client.post(f"/book_metadata/{book.filename}", json={"title": "x"})
    assert r.status_code == 401


def test_post_metadata_updates_fields(standard_client, book):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": "Renamed", "author": "Other", "genre": "fiction", "tags": []},
    )
    assert r.status_code == 200
    db.session.refresh(book)
    assert book.title == "Renamed"
    assert book.author == "Other"
    assert book.genre == "fiction"


def test_post_metadata_creates_user_tags(standard_client, book, standard_user):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "", "tags": ["scifi", "favorite"]},
    )
    assert r.status_code == 200
    tags = Tag.query.filter_by(user_id=standard_user.id).all()
    assert {t.name for t in tags} == {"scifi", "favorite"}


def test_post_metadata_status_tag_writes_bookmark(standard_client, book, standard_user):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "", "tags": ["Finished"]},
    )
    assert r.status_code == 200
    bookmark = Bookmark.query.filter_by(
        user_id=standard_user.id, book_id=book.id
    ).first()
    assert bookmark is not None
    assert bookmark.status == BookProgressChoice.FINISHED


def test_post_metadata_status_tag_clears_to_unread(standard_client, book, standard_user):
    # First mark Finished
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "", "tags": ["Finished"]},
    )
    # Then submit with no progress tag — should reset to UNREAD
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "", "tags": []},
    )
    bookmark = Bookmark.query.filter_by(
        user_id=standard_user.id, book_id=book.id
    ).first()
    assert bookmark.status == BookProgressChoice.UNREAD


def test_get_metadata_lists_progress_tag_for_authenticated(standard_client, book, standard_user):
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "", "tags": ["In Progress", "scifi"]},
    )
    r = standard_client.get(f"/book_metadata/{book.filename}")
    tags = r.get_json()["tags"]
    assert "In Progress" in tags
    assert "scifi" in tags


def test_anonymous_metadata_omits_tags(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.get_json()["tags"] == []
