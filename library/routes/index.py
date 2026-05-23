import os

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user

from ..choices import BookProgressChoice, UserRoleChoice
from ..models import Book, Bookmark, Tag, book_tags, db
from ..utils import (
    cover_mimetype,
    epub_text_size,
    guess_cover_mimetype_from_bytes,
    read_epub_cover,
)
from ._helpers import commit_or_rollback, get_book_or_404, json_admin_required

index_blueprint = Blueprint("index_routes", __name__)

BOOKS_PER_LOAD = 8


VIEW_ALL = "all"
VIEW_MINE = "mine"


def _normalize_view(view):
    if view == VIEW_MINE and not current_user.is_authenticated:
        return VIEW_ALL
    return view


def _filtered_book_query(filters=None, view=VIEW_ALL):
    """Build the base Book query with access, view, and filter WHERE clauses
    applied. Returns None when the request can't possibly match (e.g. tag
    filter requested by an anonymous user)."""
    query = Book.query

    if (
        not current_user.is_authenticated
        or current_user.role == UserRoleChoice.STANDARD
    ):
        query = query.filter(Book.access_level == "standard")

    if current_user.is_authenticated:
        query = query.outerjoin(
            Book.bookmarks.and_(Bookmark.user_id == current_user.id)
        ).outerjoin(Book.tags.and_(Tag.user_id == current_user.id))

    if view == VIEW_MINE:
        query = query.filter(Bookmark.status.in_([
            BookProgressChoice.IN_PROGRESS,
            BookProgressChoice.FINISHED,
        ]))

    if filters:
        for attr, column in (
            ("title", Book.title),
            ("author", Book.author),
            ("genre", Book.genre),
        ):
            if value := filters.get(attr):
                for word in value.split():
                    query = query.filter(column.ilike(f"%{word}%"))

        if tags := filters.get("tags"):
            if not current_user.is_authenticated:
                return None

            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
            tag_filters = []
            if BookProgressChoice.UNREAD.value in tags:
                tag_filters.append(
                    db.or_(
                        Bookmark.id.is_(None),
                        Bookmark.status == BookProgressChoice.UNREAD,
                    )
                )

            progress_tags, other_tags = [], []
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

    return query


def get_covers(offset=0, limit=BOOKS_PER_LOAD, filters=None, view=VIEW_ALL):
    """Return the next batch of book covers.

    view='all'  → every accessible book, newest first by created_at.
    view='mine' → only books the user has started (IN_PROGRESS or FINISHED),
                  ordered by last_read so the most recently opened is first.
                  Falls back to 'all' for anonymous users.
    """
    view = _normalize_view(view)
    query = _filtered_book_query(filters, view)
    if query is None:
        return []

    if view == VIEW_MINE:
        query = query.order_by(Bookmark.last_read.desc(), Book.created_at.desc())
    else:
        query = query.order_by(Book.created_at.desc())

    return [
        {
            "filename": book.filename,
            "cover": url_for("index_routes.cover", filename=book.filename),
            "length": _book_text_size(book),
        }
        for book in query.offset(offset).limit(limit).all()
    ]


def _book_text_size(book) -> int:
    """Cached EPUB text size for `book`, in bytes. Used to size spine thickness
    in the bookshelf view. Cached per (book_id, file mtime) since text size
    only changes if the EPUB is rewritten on disk."""
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
    try:
        mtime = int(os.path.getmtime(epub_path))
    except OSError:
        return 0

    # Local import to avoid circular import via library/__init__.py.
    from .. import cache

    cache_key = f"length:{book.id}:{mtime}"
    size = cache.get(cache_key)
    if size is None:
        size = epub_text_size(epub_path)
        cache.set(cache_key, size, timeout=86400)
    return size


def count_books(filters=None, view=VIEW_ALL):
    """Count of books visible to the current user under the given view+filters.
    Used to cap the number of loading skeletons rendered on the home page."""
    view = _normalize_view(view)
    query = _filtered_book_query(filters, view)
    if query is None:
        return 0
    # distinct() so the count isn't inflated by multi-tag join duplication.
    return query.distinct().count()


def _requested_view():
    view = request.args.get("view", VIEW_ALL)
    return view if view in (VIEW_ALL, VIEW_MINE) else VIEW_ALL


@index_blueprint.route("/")
def index():
    """Render the initial page with the first batch of book covers."""
    view = _requested_view()
    images = get_covers(0, BOOKS_PER_LOAD, view=view)
    total = count_books(view=view)
    return render_template(
        "index.html", images=images, current_view=view, total_books=total
    )


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
    view = _requested_view()
    images = get_covers(offset, BOOKS_PER_LOAD, filters, view=view)
    response = jsonify(images)
    # Frontend uses this to cap the number of loading skeletons it renders.
    response.headers["X-Total-Count"] = str(count_books(filters, view))
    return response


@index_blueprint.route("/cover/<filename>")
def cover(filename):
    """Serve a book's cover with long-lived caching keyed on file mtime.

    Two layers of caching:
      1. Server-side: cover bytes memoized in flask-caching keyed on
         (book_id, mtime). Avoids re-extracting from the zip on every request.
      2. Client-side: ETag-based 304 response, plus Cache-Control: 1 year.
    """
    book = get_book_or_404(filename)
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
    if not os.path.exists(epub_path):
        abort(404, description="Cover not found")

    mtime = int(os.path.getmtime(epub_path))
    etag = f"{book.id}-{mtime}"
    if request.if_none_match.contains(etag):
        return "", 304

    # Imported here (not at module top) to break a circular import:
    # library/__init__.py -> routes -> here -> library.cache.
    from .. import cache

    cache_key = f"cover:{book.id}:{mtime}"
    cover_bytes = cache.get(cache_key)
    if cover_bytes is None:
        cover_bytes = read_epub_cover(epub_path, book.cover_path)
        cache.set(cache_key, cover_bytes, timeout=86400)

    response = make_response(cover_bytes)
    response.headers["Content-Type"] = (
        guess_cover_mimetype_from_bytes(cover_bytes)
        or cover_mimetype(book.cover_path or "")
    )
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
