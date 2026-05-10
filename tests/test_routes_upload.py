import io
import os

from library.models import Book, db
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
        "/upload_book",
        data={"file": (io.BytesIO(epub), "anything.epub")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 401


def test_upload_book_rejects_non_epub(standard_client):
    r = standard_client.post(
        "/upload_book",
        data={"file": (io.BytesIO(b"not an epub"), "foo.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


def test_upload_book_returns_metadata_and_writes_file(standard_client, app):
    epub = build_epub3(title="Brave New World", author="Aldous Huxley")
    r = standard_client.post(
        "/upload_book",
        data={"file": (io.BytesIO(epub), "incoming.epub")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_json()
    payload = r.get_json()
    assert payload["title"] == "Brave New World"
    assert payload["author"] == "Aldous Huxley"
    assert payload["filename"].endswith(".epub")
    # Cover comes back as a data URL because no Book row exists yet
    assert payload["cover"].startswith("data:image/")
    # File was renamed and written to BOOK_DIR
    final_path = os.path.join(app.config["BOOK_DIR"], payload["filename"])
    assert os.path.exists(final_path)


# --- /upload_book_metadata ------------------------------------------------------


def test_upload_book_metadata_creates_book_row(standard_client, app, book_dir):
    # Pretend a previous /upload_book ran: the file is on disk under its
    # post-rename name, no Book row exists yet.
    filename = "PreUploaded__Author.epub"
    (book_dir / filename).write_bytes(build_epub3(title="PreUploaded", author="Author"))

    r = standard_client.post(
        "/upload_book_metadata",
        json={
            "original_filename": filename,
            "new_filename": filename,
            "title": "PreUploaded",
            "author": "Author",
            "genre": "fiction",
            "cover_path": "OEBPS/cover.png",
        },
    )
    assert r.status_code == 200
    assert Book.query.filter_by(filename=filename).first() is not None


def test_upload_book_metadata_renames_file_when_changed(standard_client, app, book_dir):
    original = "AAA__BBB.epub"
    renamed = "CCC__DDD.epub"
    (book_dir / original).write_bytes(build_epub3())

    r = standard_client.post(
        "/upload_book_metadata",
        json={
            "original_filename": original,
            "new_filename": renamed,
            "title": "T",
            "author": "A",
            "genre": "",
            "cover_path": "OEBPS/cover.png",
        },
    )
    assert r.status_code == 200
    assert not (book_dir / original).exists()
    assert (book_dir / renamed).exists()
