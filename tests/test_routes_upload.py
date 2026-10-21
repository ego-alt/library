import io
import os

from library.models import Book
from library.routes.upload import generate_filename
from tests._epub_builder import build_epub3

# --- generate_filename ----------------------------------------------------------


def test_generate_filename_slugifies_and_concats(tmp_path):
    assert generate_filename("Foo Bar", "Jane Doe", str(tmp_path)) == "Foo_Bar__Jane_Doe.epub"


def test_generate_filename_avoids_disk_collisions(tmp_path):
    (tmp_path / "Foo__Bar.epub").write_bytes(b"")
    assert generate_filename("Foo", "Bar", str(tmp_path)) == "Foo__Bar_2.epub"
    (tmp_path / "Foo__Bar_2.epub").write_bytes(b"")
    assert generate_filename("Foo", "Bar", str(tmp_path)) == "Foo__Bar_3.epub"


def test_generate_filename_strips_unsafe_chars(tmp_path):
    assert generate_filename("../etc/passwd", "x/y", str(tmp_path)) == "etcpasswd__xy.epub"


def test_generate_filename_handles_empty_input(tmp_path):
    assert generate_filename("", "", str(tmp_path)) == "untitled__untitled.epub"


# --- /upload_book ---------------------------------------------------------------


def test_upload_book_requires_auth(client):
    epub = build_epub3()
    r = client.post(
        "/upload_book", data={"file": (io.BytesIO(epub), "anything.epub")}, content_type="multipart/form-data"
    )
    assert r.status_code == 401


def test_upload_book_rejects_non_epub(standard_client):
    r = standard_client.post(
        "/upload_book", data={"file": (io.BytesIO(b"not an epub"), "foo.txt")}, content_type="multipart/form-data"
    )
    assert r.status_code == 400


def _stage(client, **kwargs):
    epub = build_epub3(**kwargs)
    r = client.post(
        "/upload_book", data={"file": (io.BytesIO(epub), "incoming.epub")}, content_type="multipart/form-data"
    )
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_upload_book_stages_file_without_adding_it(standard_client, app, book_dir):
    payload = _stage(standard_client, title="Brave New World", author="Aldous Huxley")
    assert payload["title"] == "Brave New World"
    assert payload["author"] == "Aldous Huxley"
    assert "filename" not in payload
    # Cover comes back as a data URL because no Book row exists yet
    assert payload["cover"].startswith("data:image/")
    # Staged under .incoming/, not in the library yet
    assert (book_dir / ".incoming" / f"{payload['upload_id']}.epub").exists()
    assert [p.name for p in book_dir.glob("*.epub")] == []
    assert Book.query.count() == 0


def test_upload_book_accepts_epub2_with_ncx_only(standard_client, monkeypatch):
    """EPUB 2 books have an NCX table of contents and no nav document."""
    from ebooklib import epub as ebooklib_epub

    monkeypatch.setattr(
        ebooklib_epub.EpubBook, "get_items_of_type", lambda self, kind: [] if kind == ebooklib_epub.EpubNav else []
    )
    assert _stage(standard_client)["upload_id"]


def test_confirm_moves_file_into_library_with_generated_name(standard_client, standard_user, book_dir):
    payload = _stage(standard_client, title="Brave New World", author="Aldous Huxley")
    r = standard_client.post(
        "/upload_book_metadata",
        json={
            "upload_id": payload["upload_id"],
            "title": "Brave New World (Revised)",
            "author": "Aldous Huxley",
            "genre": "fiction",
            "tags": ["dystopia", " ", "dystopia"],
            "cover_path": payload["cover_path"],
        },
    )
    assert r.status_code == 200, r.get_json()
    book = r.get_json()["book"]
    assert book["filename"] == "Brave_New_World_Revised__Aldous_Huxley.epub"
    assert book["cover"].startswith(f"/cover/{book['filename']}?v=")
    assert (book_dir / book["filename"]).exists()
    assert not (book_dir / ".incoming" / f"{payload['upload_id']}.epub").exists()
    row = Book.query.filter_by(filename=book["filename"]).one()
    assert row.uploaded_by == standard_user.id
    tags = standard_client.get(f"/book_metadata/{book['filename']}").get_json()["tags"]
    assert tags == ["dystopia"]


def test_confirm_rejects_unknown_or_malicious_upload_ids(standard_client, book_dir):
    for upload_id in ("../../etc/passwd", "0" * 32, None, 5):
        r = standard_client.post("/upload_book_metadata", json={"upload_id": upload_id, "title": "T", "author": "A"})
        assert r.status_code == 400
    assert Book.query.count() == 0


def test_cancel_discards_staged_upload(standard_client, book_dir):
    payload = _stage(standard_client)
    staged = book_dir / ".incoming" / f"{payload['upload_id']}.epub"
    assert staged.exists()
    assert standard_client.delete(f"/upload_book/{payload['upload_id']}").status_code == 200
    assert not staged.exists()
    # Unknown or bad ids are a harmless no-op.
    assert standard_client.delete("/upload_book/..%2F..%2Fx").status_code in (200, 404)


def test_stale_staged_uploads_are_swept(standard_client, book_dir):
    import time

    old = _stage(standard_client)
    staged = book_dir / ".incoming" / f"{old['upload_id']}.epub"
    two_days_ago = time.time() - 2 * 24 * 3600
    os.utime(staged, (two_days_ago, two_days_ago))
    _stage(standard_client)
    assert not staged.exists()
