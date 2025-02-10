from datetime import datetime
from flask import Blueprint, current_app, jsonify, request, render_template
from flask_login import current_user
from models import Book, db, Bookmark, BookProgressChoice
from utils import get_epub_content
import logging


read_blueprint = Blueprint("read_routes", __name__)


@read_blueprint.route("/read/<filename>")
def read_book(filename):
    """Render the in-browser epub reader."""
    return render_template("reader.html")


@read_blueprint.route("/load_book/<filename>")
def load_book(filename):
    """Load the book and return the book data."""
    if current_user.is_authenticated:
        book = Book.query.filter_by(filename=filename).first()
        bookmark = Bookmark.query.filter_by(
            user_id=current_user.id, book_id=book.id
        ).first()
        if not bookmark:
            bookmark = Bookmark(user_id=current_user.id, book_id=book.id)
            db.session.add(bookmark)
            db.session.commit()

        if bookmark.status == BookProgressChoice.UNREAD:
            bookmark.status = BookProgressChoice.IN_PROGRESS
            logging.info(
                f"Setting status to IN_PROGRESS for book {book.id} and user {current_user.id}"
            )
            db.session.commit()
    try:
        book_data = get_epub_content(current_app.config["BOOK_DIR"], filename)
        logging.info(
            f"Successfully processed book with {book_data['image_count']} images"
        )
        return jsonify(book_data)
    except Exception as e:
        logging.error(f"Error processing epub: {str(e)}")
        return jsonify({"error": str(e)}), 500


@read_blueprint.route("/bookmark/<filename>", methods=["GET", "POST"])
def bookmark(filename):
    """Bookmark the current chapter of the book."""
    if not current_user.is_authenticated:
        return jsonify({"message": "Authentication required."}), 200

    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({"error": "Book not found"}), 404

    if request.method == "POST":
        data = request.get_json()
        bookmark = Bookmark.query.filter_by(
            user_id=current_user.id, book_id=book.id
        ).first()
        bookmark.chapter_index = data.get("chapter_index", 0)
        bookmark.position = data.get("position", 0)
        bookmark.last_read = datetime.utcnow()

        try:
            db.session.commit()
            return jsonify({"message": "Bookmark updated successfully"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # GET request - retrieve bookmark
    bookmark = Bookmark.query.filter_by(
        user_id=current_user.id, book_id=book.id
    ).first()

    if not bookmark:
        return jsonify({"chapter_index": 0, "position": 0})

    return jsonify(
        {"chapter_index": bookmark.chapter_index, "position": bookmark.position}
    )


@read_blueprint.route("/tag_finished/<filename>", methods=["POST"])
def tag_finished(filename):
    """Tag the book as finished."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    book = Book.query.filter_by(filename=filename).first()
    if not book:
        return jsonify({"error": "Book not found"}), 404

    bookmark = Bookmark.query.filter_by(
        user_id=current_user.id, book_id=book.id
    ).first()
    bookmark.status = BookProgressChoice.FINISHED
    logging.info(
        f"Setting status to FINISHED for book {book.id} and user {current_user.id}"
    )
    db.session.commit()
    return jsonify({"message": "Book tagged as finished"})
