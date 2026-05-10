from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    request,
    render_template,
    send_from_directory,
    url_for,
)
from flask_login import current_user
from ..models import db, Book, Bookmark, Tag, book_tags
from ..choices import BookProgressChoice, UserRoleChoice
import os
from ._helpers import commit_or_rollback, get_book_or_404, json_admin_required
from ..utils import cover_mimetype, read_epub_cover


index_blueprint = Blueprint("index_routes", __name__)

BOOKS_PER_LOAD = 8


def get_covers(offset=0, limit=BOOKS_PER_LOAD, filters=None):
    query = Book.query

    if (
        not current_user.is_authenticated
        or current_user.role == UserRoleChoice.STANDARD
    ):
        query = query.filter(Book.access_level == "standard")

    # Add joins early if user is authenticated
    if current_user.is_authenticated:
        query = query.outerjoin(
            Book.bookmarks.and_(Bookmark.user_id == current_user.id)
        ).outerjoin(Book.tags.and_(Tag.user_id == current_user.id))

    if filters:
        # Apply text filters for title, author, and genre
        for attr, column in (
            ("title", Book.title),
            ("author", Book.author),
            ("genre", Book.genre),
        ):
            if value := filters.get(attr):
                for word in value.split():
                    query = query.filter(column.ilike(f"%{word}%"))

        # Apply tag filters if provided
        if tags := filters.get("tags"):
            if not current_user.is_authenticated:
                return []

            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
            tag_filters = []

            # Handle unread books
            if BookProgressChoice.UNREAD.value in tags:
                tag_filters.append(
                    db.or_(
                        Bookmark.id.is_(None),
                        Bookmark.status == BookProgressChoice.UNREAD,
                    )
                )

            # Handle progress tags and other tags in a single pass
            progress_tags = []
            other_tags = []
            for tag in tags:
                if tag in (BookProgressChoice.IN_PROGRESS.value, BookProgressChoice.FINISHED.value):
                    progress_tags.append(tag)
                elif tag != BookProgressChoice.UNREAD.value:
                    other_tags.append(tag)

            if progress_tags:
                tag_filters.append(Bookmark.status.in_(progress_tags))
            if other_tags:
                tag_filters.append(Tag.name.in_(other_tags))

            if tag_filters:
                query = query.filter(db.or_(*tag_filters))

    if current_user.is_authenticated:
        query = query.order_by(Bookmark.last_read.desc(), Book.created_at.desc())
    else:
        query = query.order_by(Book.created_at.desc())

    return [
        {
            "filename": book.filename,
            "cover": url_for("index_routes.cover", filename=book.filename),
        }
        for book in query.offset(offset).limit(limit).all()
    ]


@index_blueprint.route("/")
def index():
    """Render the initial page with the first batch of book covers."""
    images = get_covers(0, BOOKS_PER_LOAD)
    return render_template("index.html", images=images)


@index_blueprint.route("/load_more/<int:offset>", methods=["GET"])
def load_more(offset):
    filters = {
        "title": request.args.get("title"),
        "author": request.args.get("author"),
        "genre": request.args.get("genre"),
        "tags": request.args.get("tags"),
    }
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    images = get_covers(offset, BOOKS_PER_LOAD, filters)
    return jsonify(images)


@index_blueprint.route("/cover/<filename>")
def cover(filename):
    """Serve a book's cover with long-lived caching keyed on file mtime."""
    book = get_book_or_404(filename)
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
    if not os.path.exists(epub_path):
        abort(404, description="Cover not found")

    mtime = int(os.path.getmtime(epub_path))
    etag = f"{book.id}-{mtime}"
    if request.if_none_match.contains(etag):
        return "", 304

    cover_bytes = read_epub_cover(epub_path, book.cover_path)
    response = make_response(cover_bytes)
    response.headers["Content-Type"] = cover_mimetype(book.cover_path or "")
    response.headers["Cache-Control"] = "public, max-age=31536000"
    response.set_etag(etag)
    return response


@index_blueprint.route("/download/<filename>")
def download(filename):
    """Serve the EPUB file for download, respecting per-book access level."""
    book = get_book_or_404(filename)

    if book.access_level != "standard" and (
        not current_user.is_authenticated
        or current_user.role == UserRoleChoice.STANDARD
    ):
        return jsonify({"error": "Forbidden"}), 403

    return send_from_directory(
        current_app.config["BOOK_DIR"], filename, as_attachment=True
    )


@index_blueprint.route("/book/<filename>", methods=["DELETE"])
@json_admin_required
def delete_book(filename):
    """Permanently remove a book — DB row, join-table rows, and the EPUB file."""
    book = get_book_or_404(filename)
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)

    with commit_or_rollback():
        # Defensively clear book_tags rows: existing DBs don't have ON DELETE
        # CASCADE on the join table, so the orphan rows would be left behind.
        db.session.execute(
            book_tags.delete().where(book_tags.c.book_id == book.id)
        )
        db.session.delete(book)

    if os.path.exists(epub_path):
        try:
            os.remove(epub_path)
        except OSError as e:
            current_app.logger.warning(f"Removed DB row but failed to unlink {epub_path}: {e}")

    return jsonify({"message": "Book deleted"})
