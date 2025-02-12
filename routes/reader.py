from datetime import datetime
from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    render_template,
    Response,
    stream_with_context,
)
from flask_caching import Cache
from flask_login import current_user
from models import Book, db, Bookmark, BookProgressChoice
from utils import get_epub_content, rotate_list
import logging
import json
import time


read_blueprint = Blueprint("read_routes", __name__)


@read_blueprint.route("/read/<filename>")
def read_book(filename):
    """Render the in-browser epub reader."""
    return render_template("reader.html")


@read_blueprint.route("/load_book/<filename>")
def load_book(filename):
    """Load the book and return the book data as a stream."""
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
        return Response(
            stream_with_context(
                stream_book_content(
                    epub_dir=current_app.config["BOOK_DIR"],
                    epub_path=filename,
                    book_title=book.title,
                    book_author=book.author,
                    start_chapter=bookmark.chapter_index,
                    chapter_pos=bookmark.position,
                )
            ),
            content_type="application/x-ndjson",
        )
    except Exception as e:
        logging.error(f"Error processing epub: {str(e)}")
        return jsonify({"error": str(e)}), 500


def stream_book_content(
    epub_dir: str,
    epub_path: str,
    book_title: str,
    book_author: str,
    start_chapter: int,
    chapter_pos: float,
):
    """Stream book content as newline-delimited JSON."""
    try:
        cache_key = f'book_content_{epub_path}'
        cache = current_app.extensions['cache']

        start = time.perf_counter()
        book_data = cache.get(cache_key)
        
        if book_data is None:
            book_data = get_epub_content(epub_dir, epub_path)
            cache[cache_key] = book_data
            
        end = time.perf_counter()
        logging.info(f"Time taken to process epub content: {end - start:.3f} seconds")
        toc = [chapter["title"] for chapter in book_data["chapters"]]

        # Send initial metadata
        yield (
            json.dumps(
                {
                    "type": "metadata",
                    "title": book_title,
                    "author": book_author,
                    "image_count": book_data["image_count"],
                    "table_of_contents": toc,
                    "start_chapter": start_chapter,
                    "chapter_pos": chapter_pos,
                }
            )
            + "\n"
        )

        chapters = rotate_list(book_data["chapters"], n=-start_chapter)
        for i, chapter in enumerate(chapters):
            index = (i + start_chapter) % len(toc)
            yield (
                json.dumps(
                    {
                        "type": "chapter",
                        "index": index,
                        "title": chapter.get("title", f"Chapter {index + 1}"),
                        "content": chapter["content"],
                    }
                )
                + "\n"
            )

    except Exception as e:
        yield json.dumps({"type": "error", "message": str(e)}) + "\n"


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
