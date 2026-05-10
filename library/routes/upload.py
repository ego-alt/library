import base64
from ebooklib import epub
from flask import Blueprint, current_app, jsonify, request
from ..models import Book, db
import re
from ._helpers import commit_or_rollback, json_login_required
from ..utils import (
    cover_mimetype,
    extract_metadata,
    get_epub_cover_path,
    read_epub_cover,
)
import os
import uuid


upload_blueprint = Blueprint("upload_routes", __name__)


def _slugify(value: str) -> str:
    value = re.sub(r"[.,'\"]", "", value)
    value = re.sub(r"\s+", "_", value)
    # Strip anything that's not a safe filename char.
    value = re.sub(r"[^A-Za-z0-9_\-]", "", value)
    return value or "untitled"


def generate_filename(title: str, author: str, book_dir: str) -> str:
    """Build a unique <title>__<author>.epub filename, avoiding collisions on disk."""
    base = f"{_slugify(title)}__{_slugify(author)}"
    candidate = f"{base}.epub"
    i = 2
    while os.path.exists(os.path.join(book_dir, candidate)):
        candidate = f"{base}_{i}.epub"
        i += 1
    return candidate


@upload_blueprint.route("/upload_book", methods=["POST"])
@json_login_required
def upload_book():
    """Endpoint to save the uploaded EPUB and return pre-populated metadata."""
    # Check for the file in the request
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Validate file format
    if not file.filename.endswith(".epub"):
        return jsonify(
            {"error": "Invalid file format. Please upload an EPUB file"}
        ), 400

    # Use a temporary filename with timestamp to ensure uniqueness
    temp_filename = f"temp_{uuid.uuid4().hex}.epub"
    temp_file_path = os.path.join(current_app.config["BOOK_DIR"], temp_filename)
    file.save(temp_file_path)
    current_app.logger.info(f"Temporarily saved uploaded file to {temp_file_path}")

    # Read the EPUB file to extract metadata
    try:
        epub_book = epub.read_epub(temp_file_path)
        table_of_contents = epub_book.get_items_of_type(epub.EpubNav)
        if not table_of_contents:
            os.remove(temp_file_path)
            return jsonify(
                {
                    "error": "Uploaded EPUB does not contain a table of contents. Quality is questionable."
                }
            ), 400

        metadata = extract_metadata(epub_book)
        title, author = metadata.get("title", ""), metadata.get("author", "")
        filename = generate_filename(title, author, current_app.config["BOOK_DIR"])

        # Rename the file to standardized name
        final_file_path = os.path.join(current_app.config["BOOK_DIR"], filename)
        os.rename(temp_file_path, final_file_path)
        current_app.logger.info(f"Renamed file to {final_file_path}")

        cover_path = get_epub_cover_path(final_file_path)
        cover_bytes = read_epub_cover(final_file_path, cover_path)
        cover_data_url = (
            f"data:{cover_mimetype(cover_path)};base64,"
            f"{base64.b64encode(cover_bytes).decode('utf-8')}"
        )

        # Cover comes back as an inline data URL because no Book row exists yet
        # to serve via the cached /cover route.
        return jsonify(
            {
                "filename": filename,
                "title": title,
                "author": author,
                "cover": cover_data_url,
                "cover_path": cover_path,
            }
        )

    except Exception as e:
        # Clean up the temporary file if anything goes wrong
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        current_app.logger.error(f"Failed to process EPUB file: {str(e)}")
        return jsonify({"error": "Failed to process EPUB file: " + str(e)}), 500


@upload_blueprint.route("/upload_book_metadata", methods=["POST"])
@json_login_required
def upload_book_metadata():
    """Endpoint to save metadata for a newly uploaded book (creating a new DB record)."""
    data = request.get_json()
    original_filename = data.get("original_filename")
    new_filename = data.get("new_filename")
    if not new_filename:
        return jsonify({"error": "Missing new filename"}), 400

    if original_filename != new_filename:
        try:
            original_filepath = os.path.join(
                current_app.config["BOOK_DIR"], original_filename
            )
            new_filepath = os.path.join(current_app.config["BOOK_DIR"], new_filename)
            os.rename(original_filepath, new_filepath)
            current_app.logger.info(
                f"Renamed file from {original_filepath} to {new_filepath}"
            )
        except Exception as e:
            current_app.logger.error(f"Failed to rename file: {str(e)}")
            return jsonify({"error": "Failed to rename file: " + str(e)}), 500

    try:
        with commit_or_rollback():
            db.session.add(
                Book(
                    title=data.get("title"),
                    author=data.get("author"),
                    genre=data.get("genre"),
                    filename=new_filename,
                    cover_path=data.get("cover_path"),
                    access_level="standard",
                )
            )
        return jsonify({"message": "Book added successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
