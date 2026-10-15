import os

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from ..choices import AccessLevelChoice, UserRoleChoice
from ..models import Bookmark, BookProgressChoice, Tag, book_tags, db
from ..utils import display_author, update_epub_cover
from ._helpers import (
    commit_or_rollback,
    cover_url,
    get_book_or_404,
    json_login_required,
)

metadata_blueprint = Blueprint("metadata_routes", __name__)

def _book_status(book_id: int, user_id: int) -> str:
    bookmark = Bookmark.query.filter_by(book_id=book_id, user_id=user_id).first()
    return (bookmark.status if bookmark else BookProgressChoice.UNREAD).value


def _list_book_tags(book_id: int, user_id: int) -> list[str]:
    """Return the custom tag names a user has on a book. Reading status is
    separate (see _book_status)."""
    user_tag_names = [
        name
        for (name,) in db.session.query(Tag.name)
        .join(
            book_tags,
            db.and_(
                book_tags.c.tag_id == Tag.id,
                book_tags.c.book_id == book_id,
                book_tags.c.user_id == user_id,
            ),
        )
        .all()
    ]
    return user_tag_names


def _set_bookmark_status(book_id: int, user_id: int, status_value: str):
    """Set the user's reading status for a book."""
    new_status = BookProgressChoice(status_value)
    bookmark = Bookmark.query.filter_by(book_id=book_id, user_id=user_id).first()

    if bookmark is None:
        if new_status == BookProgressChoice.UNREAD:
            return
        db.session.add(
            Bookmark(user_id=user_id, book_id=book_id, status=new_status)
        )
    else:
        bookmark.status = new_status


@metadata_blueprint.route("/book_metadata/<filename>", methods=["GET", "POST"])
def book_metadata(filename):
    """Get or update book metadata."""
    book = get_book_or_404(filename)

    if request.method == "POST":
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        data = request.get_json()
        # Title, author and genre are shared by everyone, so only admins edit
        # them. Anyone signed in sets their own tags and reading status.
        if current_user.role == UserRoleChoice.ADMIN:
            book.title = (data.get("title") or book.title).strip()[:200]
            book.author = (data.get("author") or book.author).strip()[:200]
            if "genre" in data:
                book.genre = (data.get("genre") or "").strip()[:100] or None

        # Access level is admin-only to change. Non-admins (and unknown values)
        # leave it untouched — the toggle isn't rendered for them either.
        if (
            current_user.role == UserRoleChoice.ADMIN
            and "access_level" in data
            and data["access_level"] in (c.value for c in AccessLevelChoice)
        ):
            book.access_level = data["access_level"]

        custom_tag_names = [t.strip() for t in data.get("tags", []) if t.strip()]
        status_value = data.get("status")
        if status_value is not None and status_value not in {
            c.value for c in BookProgressChoice
        }:
            return jsonify({"error": "Unknown reading status"}), 400

        try:
            with commit_or_rollback():
                # Replace this user's custom tags for the book
                db.session.execute(
                    book_tags.delete().where(
                        db.and_(
                            book_tags.c.book_id == book.id,
                            book_tags.c.user_id == current_user.id,
                        )
                    )
                )
                for tag_name in custom_tag_names:
                    tag = Tag.query.filter_by(
                        name=tag_name, user_id=current_user.id
                    ).first()
                    if not tag:
                        tag = Tag(name=tag_name, user_id=current_user.id)
                        db.session.add(tag)
                        db.session.flush()
                    db.session.execute(
                        book_tags.insert().values(
                            book_id=book.id,
                            tag_id=tag.id,
                            user_id=current_user.id,
                        )
                    )
                if status_value is not None:
                    _set_bookmark_status(book.id, current_user.id, status_value)
            return jsonify({"message": "Saved"})
        except Exception as e:
            current_app.logger.error(f"Failed to save metadata for {filename}: {e}")
            return jsonify({"error": "Couldn't save your changes. Try again."}), 500

    # GET request handling
    response = {
        "title": book.title,
        "author": book.author,
        "author_display": display_author(book.author),
        "genre": book.genre,
        "created_at": book.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "tags": [],
        "status": BookProgressChoice.UNREAD.value,
        "filename": book.filename,
        "cover": cover_url(book),
        "access_level": book.access_level,
    }

    if current_user.is_authenticated:
        response["tags"] = _list_book_tags(book.id, current_user.id)
        response["status"] = _book_status(book.id, current_user.id)

    return jsonify(response)


@metadata_blueprint.route("/tags")
@json_login_required
def list_user_tags():
    """Suggestions for tag autocomplete: the current user's distinct custom tag
    names, alphabetised. (Reading status has its own control.)"""
    user_tags = [
        name
        for (name,) in db.session.query(Tag.name)
        .filter(Tag.user_id == current_user.id)
        .distinct()
        .order_by(Tag.name)
        .all()
    ]
    return jsonify(user_tags)


@metadata_blueprint.route("/update_cover", methods=["POST"])
@json_login_required
def update_cover():
    """
    Update the cover image for a book. This route expects a file input named 'cover'
    and a form field 'filename' for locating the corresponding book.
    """
    if "cover" not in request.files or "filename" not in request.form:
        return jsonify({"error": "Choose an image to use as the cover."}), 400

    cover_file = request.files["cover"]
    book = get_book_or_404(request.form["filename"])
    epub_file_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)

    try:
        new_cover_bytes = cover_file.read()
        update_epub_cover(epub_file_path, new_cover_bytes)
        # The versioned URL changes with the file's mtime, so callers can swap
        # it into the grid and browsers fetch the new cover.
        return jsonify({
            "cover": cover_url(book),
            "thumb": cover_url(book, width=400),
            "thumb_small": cover_url(book, width=120),
        })
    except Exception as e:
        current_app.logger.error(f"Error updating cover: {str(e)}")
        return jsonify({"error": "Couldn't change the cover. Try a JPG or PNG."}), 500
