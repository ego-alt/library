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
from utils import rotate_list, get_epub_structure, process_chapter_content
import logging
import json
import time
import os
from llm_caller import LLMCaller


read_blueprint = Blueprint("read_routes", __name__)

llm_caller = LLMCaller()


@read_blueprint.route("/read/<filename>")
def read_book(filename):
    """Render the in-browser epub reader."""
    return render_template("reader.html")


@read_blueprint.route("/load_book/<filename>")
def load_book(filename):
    """Load the book and return the book data as a stream."""
    book = Book.query.filter_by(filename=filename).first()
    bookmark = None

    if current_user.is_authenticated:
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
                    start_chapter=bookmark.chapter_index if bookmark else 0,
                    chapter_pos=bookmark.position if bookmark else 0,
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
        full_path = os.path.join(epub_dir, epub_path)
        structure = get_epub_structure(full_path)

        yield (
            json.dumps(
                {
                    "type": "metadata",
                    "title": book_title,
                    "author": book_author,
                    "image_count": structure["image_count"],
                    "table_of_contents": [
                        f"Chapter {ch['index'] + 1}" for ch in structure["chapters"]
                    ],
                    "start_chapter": start_chapter,
                    "chapter_pos": chapter_pos,
                }
            )
            + "\n"
        )

        # Rotate chapters list based on start_chapter
        chapters = rotate_list(structure["chapters"], n=-start_chapter)

        # Stream each chapter
        for i, chapter in enumerate(chapters):
            index = (i + start_chapter) % len(structure["chapters"])
            chapter_content = process_chapter_content(
                full_path, chapter["path"], structure["images"]
            )

            yield (
                json.dumps(
                    {
                        "type": "chapter",
                        "index": index,
                        "href": chapter_content["href"],
                        "title": chapter_content["title"] or f"Chapter {index + 1}",
                        "content": chapter_content["content"],
                    }
                )
                + "\n"
            )

            # Clear references to help garbage collection
            chapter_content = None

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


@read_blueprint.route("/ask_question", methods=["POST"])
def ask_question():
    """Handle questions about highlighted text."""
    data = request.get_json()
    context = data.get("context", "")
    question = data.get("question", "")
    
    if not context or not question:
        return jsonify({"error": "Missing context or question"}), 400
        
    answer = llm_caller.ask_question(context, question)
    return jsonify({"answer": answer})
