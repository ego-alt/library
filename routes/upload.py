from ebooklib import epub
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from models import Book, db
from utils import extract_metadata, get_epub_cover, get_epub_cover_path
import os


upload_blueprint = Blueprint("upload_routes", __name__)


@upload_blueprint.route("/upload_book", methods=["POST"])
def upload_book():
    """Endpoint to save the uploaded EPUB and return pre-populated metadata."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

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

    # Check file size (e.g., limit to 10 MB)
    max_file_size = 10 * 1024 * 1024  # 10 MB
    if file.content_length > max_file_size:
        return jsonify({"error": "File size exceeds the maximum limit of 10 MB."}), 400

    # Save the file to the BOOK_DIR
    file_path = os.path.join(current_app.config["BOOK_DIR"], file.filename)
    file.save(file_path)
    current_app.logger.info(f"Saved uploaded file to {file_path}")

    # Read the EPUB file to extract metadata
    try:
        epub_book = epub.read_epub(file_path)
        table_of_contents = epub_book.get_items_of_type(epub.EpubNav)
        import logging

        logging.info(f"Table of contents: {table_of_contents}")
        if not table_of_contents:
            # TODO: Check what the table of contents looks like
            os.remove(file_path)
            return jsonify(
                {
                    "error": "Uploaded EPUB does not contain a table of contents. Quality is questionable."
                }
            ), 400

    except Exception as e:
        current_app.logger.error(f"Failed to read EPUB file: {str(e)}")
        return jsonify({"error": "Failed to read EPUB file: " + str(e)}), 500

    metadata = extract_metadata(epub_book)
    if not metadata:
        metadata = {"title": "", "author": ""}

    # Get cover image details
    cover_path = get_epub_cover_path(file_path)
    cover = get_epub_cover(file_path, cover_path)

    # Return the metadata plus file details
    return jsonify(
        {
            "filename": file.filename,
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "cover": cover,
            "cover_path": cover_path,
        }
    )


@upload_blueprint.route("/upload_book_metadata", methods=["POST"])
def upload_book_metadata():
    """Endpoint to save metadata for a newly uploaded book (creating a new DB record)."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json()
    original_filename = data.get("original_filename")
    new_filename = data.get("new_filename")
    if not new_filename:
        return jsonify({"error": "Missing new filename"}), 400

    # Ensure this file is not already in the database
    existing_book = Book.query.filter_by(filename=new_filename).first()
    if existing_book:
        return jsonify({"error": "Book with this filename already exists"}), 400

    # Define the original and new file paths
    original_filepath = os.path.join(current_app.config["BOOK_DIR"], original_filename)
    new_filepath = os.path.join(current_app.config["BOOK_DIR"], new_filename)

    # Rename the file
    try:
        os.rename(original_filepath, new_filepath)
        current_app.logger.info(
            f"Renamed file from {original_filepath} to {new_filepath}"
        )
    except Exception as e:
        current_app.logger.error(f"Failed to rename file: {str(e)}")
        return jsonify({"error": "Failed to rename file: " + str(e)}), 500

    # Create a new Book record with the submitted metadata
    new_book = Book(
        title=data.get("title"),
        author=data.get("author"),
        genre=data.get("genre"),
        filename=new_filename,
        cover_path=data.get("cover_path"),
        access_level="standard",  # or any default you wish
    )
    db.session.add(new_book)
    try:
        db.session.commit()
        return jsonify({"message": "Book added successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
