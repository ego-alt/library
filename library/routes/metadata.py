import os

from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user

from ..models import Bookmark, BookProgressChoice, Tag, book_tags, db
from ..utils import update_epub_cover
from ._helpers import (
    commit_or_rollback,
    get_book_or_404,
    json_login_required,
)

metadata_blueprint = Blueprint("metadata_routes", __name__)

PROGRESS_TAG_VALUES = {
    BookProgressChoice.IN_PROGRESS.value,
    BookProgressChoice.FINISHED.value,
}


def _list_book_tags(book_id: int, user_id: int) -> list[str]:
    """Return all tag names a user has on a book, including the bookmark
    status when it isn't the default UNREAD."""
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

    bookmark = Bookmark.query.filter_by(book_id=book_id, user_id=user_id).first()
    progress = []
    if bookmark and bookmark.status != BookProgressChoice.UNREAD:
        progress.append(bookmark.status.value)

    return progress + user_tag_names


def _set_bookmark_status(book_id: int, user_id: int, status_value: str | None):
    """Set the bookmark's status from a tag value, defaulting to UNREAD."""
    new_status = (
        BookProgressChoice(status_value) if status_value else BookProgressChoice.UNREAD
    )
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
        book.title = data.get("title", book.title)
        book.author = data.get("author", book.author)
        book.genre = data.get("genre", book.genre)

        incoming = data.get("tags", [])
        status_tag = next((t for t in incoming if t in PROGRESS_TAG_VALUES), None)
        custom_tag_names = [t for t in incoming if t not in PROGRESS_TAG_VALUES]

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
                _set_bookmark_status(book.id, current_user.id, status_tag)
            return jsonify({"message": "Metadata updated successfully"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # GET request handling
    response = {
        "title": book.title,
        "author": book.author,
        "genre": book.genre,
        "created_at": book.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "tags": [],
        "filename": book.filename,
        "cover": url_for("index_routes.cover", filename=book.filename),
    }

    if current_user.is_authenticated:
        response["tags"] = _list_book_tags(book.id, current_user.id)

    return jsonify(response)


@metadata_blueprint.route("/tags")
@json_login_required
def list_user_tags():
    """Suggestions for tag autocomplete: progress-status values first, then the
    current user's distinct custom tag names alphabetised."""
    user_tags = [
        name
        for (name,) in db.session.query(Tag.name)
        .filter(Tag.user_id == current_user.id)
        .distinct()
        .order_by(Tag.name)
        .all()
    ]
    status_tags = [c.value for c in BookProgressChoice]
    seen, ordered = set(), []
    for t in status_tags + user_tags:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return jsonify(ordered)


@metadata_blueprint.route("/update_cover", methods=["POST"])
@json_login_required
def update_cover():
    """
    Update the cover image for a book. This route expects a file input named 'cover'
    and a form field 'filename' for locating the corresponding book.
    """
    if "cover" not in request.files or "filename" not in request.form:
        return jsonify({"error": "Cover file and filename are required"}), 400

    cover_file = request.files["cover"]
    book = get_book_or_404(request.form["filename"])
    epub_file_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)

    try:
        new_cover_bytes = cover_file.read()
        update_epub_cover(epub_file_path, new_cover_bytes)
        # Cache-bust the cover URL by appending the new mtime
        cover_url = url_for("index_routes.cover", filename=book.filename)
        cover_url = f"{cover_url}?v={int(os.path.getmtime(epub_file_path))}"
        return jsonify({"cover": cover_url})
    except Exception as e:
        current_app.logger.error(f"Error updating cover: {str(e)}")
        return jsonify({"error": str(e)}), 500
