import base64
import os
import re
import time
import uuid

from ebooklib import epub
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from ..books.files import generate_filename, has_toc
from ..books.getting import _surname
from ..models import Book, Tag, book_tags, db
from ..utils import (
    cover_mimetype,
    display_author,
    extract_metadata,
    fallback_cover_svg,
    get_epub_cover_path,
    guess_cover_mimetype_from_bytes,
    read_epub_cover,
)
from ._helpers import (
    commit_or_rollback,
    cover_url,
    json_login_required,
    user_can_access_book,
)

upload_blueprint = Blueprint("upload_routes", __name__)


# Uploads wait in BOOK_DIR/.incoming/<id>.epub until the uploader confirms
# them, so an abandoned upload never shows up as a stray EPUB in the library
# (and the client never names files on disk).
INCOMING_DIRNAME = ".incoming"
INCOMING_MAX_AGE = 24 * 60 * 60  # seconds; older unconfirmed uploads are swept
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _incoming_dir() -> str:
    path = os.path.join(current_app.config["BOOK_DIR"], INCOMING_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _incoming_path(upload_id: str) -> str | None:
    if not isinstance(upload_id, str) or not _UPLOAD_ID_RE.match(upload_id):
        return None
    return os.path.join(_incoming_dir(), f"{upload_id}.epub")


def _sweep_incoming():
    """Remove unconfirmed uploads older than INCOMING_MAX_AGE."""
    now = time.time()
    folder = _incoming_dir()
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if now - os.path.getmtime(path) > INCOMING_MAX_AGE:
                os.remove(path)
        except OSError:
            pass


def _already_have(title: str, author: str) -> bool:
    """Whether the library already has this book (same title, same author's
    surname), so the review panel can say so before a second copy goes in."""
    if not title.strip():
        return False
    same_title = Book.query.filter(Book.deleted_at.is_(None), db.func.lower(Book.title) == title.strip().lower())
    return any(_surname(b.author) == _surname(author) and user_can_access_book(b) for b in same_title)


@upload_blueprint.route("/upload_book", methods=["POST"])
@json_login_required
def upload_book():
    """Stage an uploaded EPUB and return its metadata for the uploader to
    review. Nothing is added to the library until /upload_book_metadata."""
    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Choose an EPUB file to add."}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".epub"):
        return jsonify({"error": "Only .epub files can be added."}), 400

    _sweep_incoming()
    upload_id = uuid.uuid4().hex
    path = _incoming_path(upload_id)
    file.save(path)

    try:
        epub_book = epub.read_epub(path, options={"ignore_ncx": True})
        if not has_toc(path, epub_book):
            os.remove(path)
            return jsonify(
                {
                    "error": "This book has no table of contents, so it can't be "
                    "added. Re-exporting it from Calibre usually fixes this."
                }
            ), 400

        metadata = extract_metadata(epub_book) or {}
        try:
            cover_path = get_epub_cover_path(path)
            cover_bytes = read_epub_cover(path, cover_path)
            mimetype = guess_cover_mimetype_from_bytes(cover_bytes)
            mimetype = mimetype or cover_mimetype(cover_path)
            cover = (
                f"data:{mimetype};base64,{base64.b64encode(cover_bytes).decode('ascii')}"
            )
        except Exception:
            cover_path = None
            cover = (
                "data:image/svg+xml;base64,"
                + base64.b64encode(fallback_cover_svg(
                    metadata.get("title", ""), metadata.get("author", "")
                )).decode("ascii")
            )

        # Cover comes back as an inline data URL because no Book row exists yet
        # to serve via the cached /cover route.
        return jsonify(
            {
                "upload_id": upload_id,
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "cover": cover,
                "cover_path": cover_path,
                "already_have": _already_have(metadata.get("title", ""), metadata.get("author", "")),
            }
        )
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        current_app.logger.error(f"Failed to process EPUB file: {str(e)}")
        return jsonify(
            {"error": "Couldn't read this file. It may be damaged or not a real EPUB."}
        ), 400


@upload_blueprint.route("/upload_book/<upload_id>", methods=["DELETE"])
@json_login_required
def cancel_upload(upload_id):
    """The uploader closed the review panel: discard the staged file."""
    path = _incoming_path(upload_id)
    if path and os.path.exists(path):
        os.remove(path)
    return jsonify({"message": "Discarded"})


@upload_blueprint.route("/upload_book_metadata", methods=["POST"])
@json_login_required
def upload_book_metadata():
    """Confirm a staged upload: move it into the library under a filename
    generated from the (possibly edited) title and author, and create its row.
    Returns the new book in the same shape as /load_more items."""
    data = request.get_json() or {}
    path = _incoming_path(data.get("upload_id"))
    if not path or not os.path.exists(path):
        return jsonify(
            {"error": "This upload has expired. Choose the file again."}
        ), 400

    title = (data.get("title") or "").strip() or "Untitled"
    author = (data.get("author") or "").strip() or "Unknown author"
    book_dir = current_app.config["BOOK_DIR"]
    filename = generate_filename(title, author, book_dir)
    try:
        os.replace(path, os.path.join(book_dir, filename))
    except OSError as e:
        current_app.logger.error(f"Failed to move upload into library: {e}")
        return jsonify({"error": "Couldn't save the book file. Try again."}), 500

    try:
        with commit_or_rollback():
            book = Book(
                title=title[:200],
                author=author[:200],
                filename=filename,
                cover_path=data.get("cover_path"),
                access_level="standard",
                uploaded_by=current_user.id,
            )
            db.session.add(book)
            db.session.flush()
            for name in {t.strip()[:50] for t in data.get("tags", []) if t.strip()}:
                tag = Tag.query.filter_by(name=name, user_id=current_user.id).first()
                if not tag:
                    tag = Tag(name=name, user_id=current_user.id)
                    db.session.add(tag)
                    db.session.flush()
                db.session.execute(book_tags.insert().values(
                    book_id=book.id, tag_id=tag.id, user_id=current_user.id
                ))
    except Exception as e:
        current_app.logger.error(f"Failed to add book: {e}")
        # Put the file back so the uploader can retry.
        os.replace(os.path.join(book_dir, filename), path)
        return jsonify(
            {"error": "Couldn't add the book to the library. Try again."}
        ), 500

    return jsonify({
        "message": "Book added",
        "book": {
            "filename": book.filename,
            "title": book.title,
            "author": display_author(book.author),
            "cover": cover_url(book, width=400),
            "access_level": book.access_level,
        },
    })
