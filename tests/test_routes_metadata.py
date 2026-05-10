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


# --- /tags (autocomplete suggestions) -------------------------------------------


def test_list_tags_requires_auth(client):
    r = client.get("/tags")
    assert r.status_code == 401


def test_list_tags_returns_status_values_for_user_with_no_tags(standard_client):
    r = standard_client.get("/tags")
    assert r.status_code == 200
    payload = r.get_json()
    # Status values always present
    for s in ("Unread", "In Progress", "Finished"):
        assert s in payload


def test_list_tags_returns_user_custom_tags_alphabetised(standard_client, book):
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "genre": "",
              "tags": ["zeta", "alpha", "mike"]},
    )
    r = standard_client.get("/tags")
    payload = r.get_json()
    custom_only = [t for t in payload if t not in ("Unread", "In Progress", "Finished")]
    assert custom_only == ["alpha", "mike", "zeta"]


def test_list_tags_does_not_leak_other_users_tags(standard_client):
    from library.choices import UserRoleChoice
    from library.models import Tag, User

    # Seed another user's private tag directly. (Avoids juggling a second test
    # client, which trips Flask-Login's per-app-context caching of current_user
    # under the conftest's shared app context.)
    other = User(username="other", role=UserRoleChoice.STANDARD)
    other.set_password("pw")
    db.session.add(other)
    db.session.commit()
    db.session.add(Tag(name="other-private", user_id=other.id))
    db.session.commit()

    r = standard_client.get("/tags")
    assert "other-private" not in r.get_json()
