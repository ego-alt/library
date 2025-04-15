from flask import Blueprint, current_app, jsonify, request, render_template
from flask_login import current_user
from models import db, Book, Bookmark, Tag
from choices import BookProgressChoice, UserRoleChoice
import os
from utils import get_epub_cover


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
        ).outerjoin(
            Book.tags.and_(Tag.user_id == current_user.id)
        )

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
                if tag in (BookProgressChoice.IN_PROGRESS, BookProgressChoice.FINISHED):
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
            "cover": get_epub_cover(
                os.path.join(current_app.config["BOOK_DIR"], book.filename),
                book.cover_path,
            ),
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


@index_blueprint.route("/download/<filename>")
def download(filename):
    """Serve the EPUB file for download."""
    return send_from_directory(
        current_app.config["BOOK_DIR"], filename, as_attachment=True
    )
