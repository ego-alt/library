from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from models import Book, Bookmark, Tag, book_tags, db, BookProgressChoice
from utils import get_epub_cover, update_epub_cover
import os
import base64


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
    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({"error": "Book not found"}), 404

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
            db.session.commit()
            return jsonify({"message": "Metadata updated successfully"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # GET request handling
    response = {
        "title": book.title,
        "author": book.author,
        "genre": book.genre,
        "created_at": book.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "tags": [],
        "filename": book.filename,
        "cover": get_epub_cover(
            os.path.join(current_app.config["BOOK_DIR"], book.filename),
            book.cover_path,
        ),
    }

    if current_user.is_authenticated:
        response["tags"] = _list_book_tags(book.id, current_user.id)

    return jsonify(response)


@metadata_blueprint.route("/update_cover", methods=["POST"])
def update_cover():
    """
    Update the cover image for a book. This route expects a file input named 'cover'
    and a form field 'filename' for locating the corresponding book.
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    if "cover" not in request.files or "filename" not in request.form:
        return jsonify({"error": "Cover file and filename are required"}), 400

    cover_file = request.files["cover"]
    filename = request.form["filename"]

    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({"error": "Book not found"}), 404

    epub_file_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)

    try:
        new_cover_bytes = cover_file.read()
        update_epub_cover(epub_file_path, new_cover_bytes)
        new_cover_b64 = base64.b64encode(new_cover_bytes).decode("utf-8")
        return jsonify({"new_cover": new_cover_b64})
    except Exception as e:
        current_app.logger.error(f"Error updating cover: {str(e)}")
        return jsonify({"error": str(e)}), 500
