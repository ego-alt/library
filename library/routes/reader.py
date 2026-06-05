import json
import logging
import mimetypes
import os
import zipfile

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import current_user

from ..llm_caller import LLMCaller, LLMError
from ..models import Bookmark, BookProgressChoice, _utcnow, db
from ..utils import get_epub_structure, process_chapter_content, rotate_list
from ._helpers import (
    commit_or_rollback,
    get_book_or_404,
    json_login_required,
    user_can_access_book,
)

read_blueprint = Blueprint("read_routes", __name__)

llm_caller = LLMCaller()


def _llm_response(payload_key: str, fn, *args):
    try:
        return jsonify({payload_key: fn(*args)})
    except LLMError as e:
        current_app.logger.error(f"LLM call failed: {e}")
        return jsonify({"error": str(e)}), 502


@read_blueprint.route("/read/<filename>")
def read_book(filename):
    """Render the in-browser epub reader."""
    book = get_book_or_404(filename)
    if not user_can_access_book(book):
        abort(403, description="Forbidden")
    return render_template("reader.html")


@read_blueprint.route("/load_book/<filename>")
def load_book(filename):
    """Load the book and return the book data as a stream."""
    book = get_book_or_404(filename)
    if not user_can_access_book(book):
        abort(403, description="Forbidden")
    bookmark = None

    if current_user.is_authenticated:
        bookmark = Bookmark.query.filter_by(
            user_id=current_user.id, book_id=book.id
        ).first()
        if not bookmark:
            # Brand new bookmark: opening counts as starting to read.
            # (Setting status explicitly because the column default only
            # applies at flush time, leaving the attribute None on the
            # in-memory object — so the UNREAD check below would not fire.)
            bookmark = Bookmark(
                user_id=current_user.id,
                book_id=book.id,
                status=BookProgressChoice.IN_PROGRESS,
            )
            db.session.add(bookmark)
        elif bookmark.status == BookProgressChoice.UNREAD:
            bookmark.status = BookProgressChoice.IN_PROGRESS
            logging.info(
                f"Setting status to IN_PROGRESS for book {book.id} and user {current_user.id}"
            )

        bookmark.last_read = _utcnow()
        db.session.commit()

    asset_url_prefix = url_for("read_routes.book_asset", filename=filename, asset_path="")

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
                    asset_url_prefix=asset_url_prefix,
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
    asset_url_prefix: str,
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
                    "toc": structure["toc"],
                    "spine_length": structure["spine_length"],
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
                full_path, chapter["path"], structure["images"], asset_url_prefix
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


@read_blueprint.route("/book_asset/<filename>/<path:asset_path>")
def book_asset(filename, asset_path):
    """Serve a single file (image, font, etc) from inside an EPUB with long-lived caching."""
    book = get_book_or_404(filename)
    if not user_can_access_book(book):
        abort(403, description="Forbidden")
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
    if not os.path.exists(epub_path):
        abort(404, description="Book file not found")

    mtime = int(os.path.getmtime(epub_path))
    etag = f"{book.id}-{mtime}-{asset_path}"
    if request.if_none_match.contains(etag):
        return "", 304

    try:
        with zipfile.ZipFile(epub_path) as z:
            asset_bytes = z.read(asset_path)
    except KeyError:
        abort(404, description="Asset not found")

    response = make_response(asset_bytes)
    mime_type, _ = mimetypes.guess_type(asset_path)
    response.headers["Content-Type"] = mime_type or "application/octet-stream"
    response.headers["Cache-Control"] = "public, max-age=31536000"
    response.set_etag(etag)
    return response


@read_blueprint.route("/bookmark/<filename>", methods=["GET", "POST"])
def bookmark(filename):
    """Get or update the user's bookmark for the book."""
    if not current_user.is_authenticated:
        return jsonify({"message": "Authentication required."}), 200

    book = get_book_or_404(filename)

    if request.method == "POST":
        data = request.get_json()
        with commit_or_rollback():
            bookmark = Bookmark.query.filter_by(
                user_id=current_user.id, book_id=book.id
            ).first()
            if not bookmark:
                bookmark = Bookmark(user_id=current_user.id, book_id=book.id)
                db.session.add(bookmark)
            bookmark.chapter_index = data.get("chapter_index", 0)
            bookmark.position = data.get("position", 0)
            bookmark.last_read = _utcnow()
        return jsonify({"message": "Bookmark updated successfully"})

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
@json_login_required
def tag_finished(filename):
    """Tag the book as finished."""
    book = get_book_or_404(filename)

    bookmark = Bookmark.query.filter_by(
        user_id=current_user.id, book_id=book.id
    ).first()
    if not bookmark:
        bookmark = Bookmark(user_id=current_user.id, book_id=book.id)
        db.session.add(bookmark)
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

    return _llm_response("answer", llm_caller.ask_question, context, question)


@read_blueprint.route("/define_word", methods=["POST"])
def define_word():
    """Handle word definition requests."""
    data = request.get_json()
    word = data.get("word", "")
    context = data.get("context", "")

    if not word or not context:
        return jsonify({"error": "Missing word or context"}), 400

    return _llm_response("definition", llm_caller.define_word, word, context)


@read_blueprint.route("/translate_text", methods=["POST"])
def translate_text():
    data = request.json
    text = data.get("text", "")
    context = data.get("context", "")

    return _llm_response("translation", llm_caller.translate_text, text, context)
