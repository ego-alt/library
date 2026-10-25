from library.choices import BookProgressChoice
from library.models import Bookmark, Tag, db


def test_get_metadata_returns_book_fields(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["title"] == "Test Book"
    assert payload["author"] == "Test Author"
    assert payload["filename"] == book.filename
    assert payload["cover"].startswith(f"/cover/{book.filename}?v=")


def test_get_metadata_404_for_unknown_book(client):
    r = client.get("/book_metadata/missing.epub")
    assert r.status_code == 404


def test_post_metadata_requires_auth(client, book):
    r = client.post(f"/book_metadata/{book.filename}", json={"title": "x"})
    assert r.status_code == 401


def test_post_metadata_updates_fields(admin_client, book):
    r = admin_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": "Renamed", "author": "Other", "tags": []},
    )
    assert r.status_code == 200
    db.session.refresh(book)
    assert book.title == "Renamed"
    assert book.author == "Other"


def test_post_metadata_creates_user_tags(standard_client, book, standard_user):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "tags": ["scifi", "favorite"]},
    )
    assert r.status_code == 200
    tags = Tag.query.filter_by(user_id=standard_user.id).all()
    assert {t.name for t in tags} == {"scifi", "favorite"}


def test_saving_without_status_leaves_it_alone(standard_client, book, standard_user):
    standard_client.post(f"/book_metadata/{book.filename}", json={"status": "Finished"})
    standard_client.post(f"/book_metadata/{book.filename}", json={"tags": ["x"]})
    bookmark = Bookmark.query.filter_by(user_id=standard_user.id, book_id=book.id).one()
    assert bookmark.status == BookProgressChoice.FINISHED

def test_status_names_in_tags_are_plain_tags(standard_client, book):
    """Status has its own field; a tag that happens to say "Finished" is a tag."""
    standard_client.post(
        f"/book_metadata/{book.filename}", json={"tags": ["Finished", "scifi"]})
    payload = standard_client.get(f"/book_metadata/{book.filename}").get_json()
    assert payload["tags"] == ["Finished", "scifi"]
    assert payload["status"] == "Unread"

def test_status_field_sets_reading_status(standard_client, book):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "tags": ["scifi"], "status": "Finished"},
    )
    assert r.status_code == 200
    payload = standard_client.get(f"/book_metadata/{book.filename}").get_json()
    assert payload["status"] == "Finished"
    assert payload["tags"] == ["scifi"]

    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "tags": [], "status": "Unread"},
    )
    assert standard_client.get(f"/book_metadata/{book.filename}").get_json()["status"] == "Unread"


def test_unknown_status_is_rejected(standard_client, book):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author, "status": "Abandoned"},
    )
    assert r.status_code == 400


def test_anonymous_metadata_omits_tags(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.get_json()["tags"] == []


# --- access_level (admin-only books) --------------------------------------------


def test_get_metadata_exposes_access_level(client, book):
    r = client.get(f"/book_metadata/{book.filename}")
    assert r.get_json()["access_level"] == "standard"


def test_admin_can_set_access_level_restricted(admin_client, book):
    r = admin_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author,
              "tags": [], "access_level": "restricted"},
    )
    assert r.status_code == 200
    db.session.refresh(book)
    assert book.access_level == "restricted"


def test_admin_can_clear_access_level_back_to_standard(admin_client, book):
    book.access_level = "restricted"
    db.session.commit()
    r = admin_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author,
              "tags": [], "access_level": "standard"},
    )
    assert r.status_code == 200
    db.session.refresh(book)
    assert book.access_level == "standard"


def test_standard_user_cannot_change_access_level(standard_client, book):
    r = standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author,
              "tags": [], "access_level": "restricted"},
    )
    assert r.status_code == 200  # the rest of the save still succeeds
    db.session.refresh(book)
    assert book.access_level == "standard"  # but access_level is untouched


def test_admin_invalid_access_level_is_ignored(admin_client, book):
    r = admin_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author,
              "tags": [], "access_level": "superuser"},
    )
    assert r.status_code == 200
    db.session.refresh(book)
    assert book.access_level == "standard"


# --- /tags (autocomplete suggestions) -------------------------------------------


def test_list_tags_requires_auth(client):
    r = client.get("/tags")
    assert r.status_code == 401


def test_list_tags_excludes_status_values(standard_client):
    """Reading status has its own control, so it isn't suggested as a tag."""
    r = standard_client.get("/tags")
    assert r.status_code == 200
    assert r.get_json() == []


def test_list_tags_returns_user_custom_tags_alphabetised(standard_client, book):
    standard_client.post(
        f"/book_metadata/{book.filename}",
        json={"title": book.title, "author": book.author,
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


def test_standard_user_cannot_rename_shared_fields(standard_client, book):
    """Title and author are shared; only admins change them. Tags and
    status still save for everyone."""
    r = standard_client.post(f"/book_metadata/{book.filename}", json={
        "title": "Hacked", "author": "Nobody", "tags": ["mine"],
        "status": "Finished",
    })
    assert r.status_code == 200
    payload = standard_client.get(f"/book_metadata/{book.filename}").get_json()
    assert payload["title"] == "Test Book"
    assert payload["author"] == "Test Author"
    assert payload["tags"] == ["mine"]
    assert payload["status"] == "Finished"


def test_admin_can_rename(admin_client, book):
    admin_client.post(f"/book_metadata/{book.filename}", json={
        "title": "  New Title ", "author": "New Author"})
    payload = admin_client.get(f"/book_metadata/{book.filename}").get_json()
    assert payload["title"] == "New Title"
    assert "genre" not in payload
