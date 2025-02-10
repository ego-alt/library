from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from models import Book, db, Tag, book_tags, BookProgressChoice
from tag_manager import TagManager
from utils import get_epub_cover, update_epub_cover
import os
import base64


metadata_blueprint = Blueprint("metadata_routes", __name__)

BOOKMARK_ATTRIBUTES = {
    "status": [BookProgressChoice.IN_PROGRESS, BookProgressChoice.FINISHED]
}


def bulk_create_tags(book, tags: list[Tag]):
    for tag in tags:
        db.session.execute(
            book_tags.insert().values(
                book_id=book.id, tag_id=tag.id, user_id=current_user.id
            )
        )


def bulk_update_bookmark(book, field_to_update):
    tag_manager = TagManager(db.session, current_user.id)
    for key, value in field_to_update.items():
        tag_manager.update_from_virtual_tag(book.id, key, value)


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
        try:
            # First, remove all existing tags for this user and book
            db.session.execute(
                book_tags.delete().where(
                    db.and_(
                        book_tags.c.book_id == book.id,
                        book_tags.c.user_id == current_user.id,
                    )
                )
            )
            # Create/get tags and commit them
            bookmark_fields_to_update = {
                key: None for key in BOOKMARK_ATTRIBUTES.keys()
            }
            tags_to_add = []

            for tag_name in data.get("tags", []):
                next_iter = False
                for key, value in BOOKMARK_ATTRIBUTES.items():
                    if tag_name in value:
                        bookmark_fields_to_update[key] = tag_name
                        next_iter = True
                        break

                if next_iter:
                    continue

                tag = Tag.query.filter_by(
                    name=tag_name, user_id=current_user.id
                ).first()

                if not tag:
                    tag = Tag(name=tag_name, user_id=current_user.id)
                    db.session.add(tag)
                    db.session.flush()  # This assigns the ID without committing

                tags_to_add.append(tag)

            bulk_create_tags(book, tags_to_add)
            bulk_update_bookmark(book, bookmark_fields_to_update)
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
            os.path.join(current_app.config["BOOK_DIR"], book.filename), book.cover_path
        ),
    }

    # Only include tags if user is authenticated
    if current_user.is_authenticated:
        # Get tags specific to this user and book
        tag_manager = TagManager(db.session, current_user.id)
        response["tags"] = tag_manager.get_all_tags(book.id)

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

    # Query the Book record by filename
    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({"error": "Book not found"}), 404

    epub_file_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)

    try:
        new_cover_bytes = cover_file.read()
        # Delegate EPUB cover replacement to our utils helper function
        update_epub_cover(epub_file_path, new_cover_bytes)
        new_cover_b64 = base64.b64encode(new_cover_bytes).decode("utf-8")
        return jsonify({"new_cover": new_cover_b64})
    except Exception as e:
        current_app.logger.error(f"Error updating cover: {str(e)}")
        return jsonify({"error": str(e)}), 500
