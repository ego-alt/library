import os
from datetime import timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    send_from_directory,
)
from flask_login import current_user

from ..choices import AccessLevelChoice, BookProgressChoice, UserRoleChoice
from ..matching import DEFAULT_MATCH_THRESHOLD, rank_matches
from ..models import Book, Bookmark, Tag, _utcnow, book_tags, db
from ..utils import (
    book_progress,
    cover_mimetype,
    display_author,
    epub_text_size,
    fallback_cover_svg,
    guess_cover_mimetype_from_bytes,
    make_thumbnail,
    read_epub_cover,
)
from ._helpers import (
    chapter_sizes,
    commit_or_rollback,
    cover_url,
    get_accessible_book_or_404,
    get_book_or_404,
    json_admin_required,
    json_login_required,
    user_can_access_book,
)

index_blueprint = Blueprint("index_routes", __name__)

# Books per request: three to four rows of the grid at desktop width.
BOOKS_PER_LOAD = 24
CONTINUE_READING_LIMIT = 3


# Library views, by reading status.
VIEW_ALL = "all"
VIEW_UNREAD = "unread"
VIEW_READING = "reading"
VIEW_FINISHED = "finished"
VIEWS = (VIEW_ALL, VIEW_UNREAD, VIEW_READING, VIEW_FINISHED)
# Views ordered by when you last read, most recent first.
_LAST_READ_VIEWS = (VIEW_READING, VIEW_FINISHED)


def _normalize_view(view):
    if view != VIEW_ALL and not current_user.is_authenticated:
        return VIEW_ALL
    return view


def _tag_match(name_clause):
    """Books carrying one of the current user's tags whose name matches."""
    return Book.id.in_(
        db.select(book_tags.c.book_id)
        .join(Tag, Tag.id == book_tags.c.tag_id)
        .where(book_tags.c.user_id == current_user.id, name_clause)
    )


def _filtered_book_query(filters=None, view=VIEW_ALL):
    """Build the base Book query with access, view and search applied.

    filters["q"] is the library's search box: every word must appear in the
    title, author, genre, or one of your tags."""
    query = Book.query.filter(Book.deleted_at.is_(None))

    if (
        not current_user.is_authenticated
        or current_user.role == UserRoleChoice.STANDARD
    ):
        query = query.filter(Book.access_level == AccessLevelChoice.STANDARD.value)

    if current_user.is_authenticated:
        query = query.outerjoin(
            Book.bookmarks.and_(Bookmark.user_id == current_user.id)
        )

    status_for_view = {
        VIEW_READING: [BookProgressChoice.IN_PROGRESS],
        VIEW_FINISHED: [BookProgressChoice.FINISHED],
    }
    if view in status_for_view:
        query = query.filter(Bookmark.status.in_(status_for_view[view]))
    elif view == VIEW_UNREAD:
        query = query.filter(db.or_(
            Bookmark.id.is_(None), Bookmark.status == BookProgressChoice.UNREAD
        ))

    if not filters:
        return query

    if q := filters.get("q"):
        for word in q.split():
            pattern = f"%{word}%"
            matches = [
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.genre.ilike(pattern),
            ]
            if current_user.is_authenticated:
                matches.append(_tag_match(Tag.name.ilike(pattern)))
            query = query.filter(db.or_(*matches))

    return query


def get_covers(offset=0, limit=BOOKS_PER_LOAD, filters=None, view=VIEW_ALL):
    """Return the next batch of book covers.

    view='all'      → every accessible book, newest first by created_at.
    view='unread'   → books you haven't started, newest first.
    view='reading' / 'finished' → by reading status, most recently read first.
    Anything but 'all' falls back to 'all' for anonymous users.
    """
    view = _normalize_view(view)
    query = _filtered_book_query(filters, view)

    if view in _LAST_READ_VIEWS:
        query = query.order_by(Bookmark.last_read.desc(), Book.created_at.desc())
    else:
        query = query.order_by(Book.created_at.desc())

    return [
        {
            "filename": book.filename,
            "title": book.title,
            "author": display_author(book.author),
            "cover": cover_url(book, width=400),
            "length": _book_text_size(book),
            "access_level": book.access_level,
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
    return query.count()


def continue_reading(limit=CONTINUE_READING_LIMIT):
    """The current user's in-progress books, most recently read first, each
    with whole-book progress. Empty for anonymous users."""
    if not current_user.is_authenticated:
        return []
    query = (
        Book.query.join(Bookmark, db.and_(
            Bookmark.book_id == Book.id, Bookmark.user_id == current_user.id
        ))
        .filter(Book.deleted_at.is_(None))
        .filter(Bookmark.status == BookProgressChoice.IN_PROGRESS)
    )
    if current_user.role == UserRoleChoice.STANDARD:
        query = query.filter(Book.access_level == AccessLevelChoice.STANDARD.value)
    rows = (
        query.add_columns(Bookmark.chapter_index, Bookmark.position)
        .order_by(Bookmark.last_read.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "filename": book.filename,
            "title": book.title,
            "author": display_author(book.author),
            "cover": cover_url(book, width=120),
            "progress": round(book_progress(chapter_sizes(book), chapter, position), 4),
        }
        for book, chapter, position in rows
    ]


def _requested_view():
    view = request.args.get("view", VIEW_ALL)
    return view if view in VIEWS else VIEW_ALL


@index_blueprint.route("/")
def index():
    """Render the initial page with the first batch of book covers."""
    view = _requested_view()
    images = get_covers(0, BOOKS_PER_LOAD, view=view)
    total = count_books(view=view)
    return render_template(
        "index.html",
        page_size=BOOKS_PER_LOAD,
        images=images,
        current_view=view,
        total_books=total,
        continue_books=continue_reading(),
    )


@index_blueprint.route("/load_more/<int:offset>", methods=["GET"])
def load_more(offset):
    q = (request.args.get("q") or "").strip()
    filters = {"q": q} if q else {}
    view = _requested_view()
    images = get_covers(offset, BOOKS_PER_LOAD, filters, view=view)
    response = jsonify(images)
    # Frontend uses this to cap the number of loading skeletons it renders.
    response.headers["X-Total-Count"] = str(count_books(filters, view))
    return response


# Thumbnail widths the grid and Continue reading ask for. Requests snap to one
# of these so the disk cache stays bounded.
THUMB_WIDTHS = (120, 400)


def _snap_width(width):
    if not width:
        return None
    return next((w for w in THUMB_WIDTHS if width <= w), THUMB_WIDTHS[-1])


@index_blueprint.route("/cover/<filename>")
def cover(filename):
    """Serve a book's cover, or a ?w=120|400 WebP thumbnail of it.

    Caching:
      1. Server-side: full cover bytes memoized in flask-caching; thumbnails
         written to instance/thumbs/ keyed on (book id, mtime, width).
      2. Client-side: ETag-based 304 response, plus Cache-Control: 1 year.
    A book whose EPUB has no usable cover gets a generated typographic one.
    """
    book = get_accessible_book_or_404(filename)
    epub_path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
    if not os.path.exists(epub_path):
        abort(404, description="Cover not found")

    mtime = int(os.path.getmtime(epub_path))
    width = _snap_width(request.args.get("w", type=int))
    etag = f"{book.id}-{mtime}-{width or 'full'}"
    if request.if_none_match.contains(etag):
        return "", 304

    # Imported here (not at module top) to break a circular import:
    # library/__init__.py -> routes -> here -> library.cache.
    from .. import cache

    cache_key = f"cover:{book.id}:{mtime}"
    cover_bytes = cache.get(cache_key)
    if cover_bytes is None:
        try:
            cover_bytes = read_epub_cover(epub_path, book.cover_path)
        except Exception as e:
            current_app.logger.info(f"No usable cover in {book.filename}: {e}")
            cover_bytes = fallback_cover_svg(book.title, display_author(book.author))
        cache.set(cache_key, cover_bytes, timeout=86400)

    mimetype = (
        guess_cover_mimetype_from_bytes(cover_bytes)
        or cover_mimetype(book.cover_path or "")
    )
    if width and mimetype != "image/svg+xml":
        thumb = _cached_thumbnail(book, mtime, width, cover_bytes)
        if thumb is not None:
            cover_bytes, mimetype = thumb, "image/webp"

    response = make_response(cover_bytes)
    response.headers["Content-Type"] = mimetype
    response.headers["Cache-Control"] = "public, max-age=31536000"
    response.set_etag(etag)
    return response


def _cached_thumbnail(book, mtime, width, cover_bytes):
    """WebP thumbnail from instance/thumbs/, generating it on first request.
    Returns None if the image can't be decoded (the caller serves the original)."""
    thumb_dir = current_app.config["THUMB_DIR"]
    path = os.path.join(thumb_dir, f"{book.id}-{mtime}-{width}.webp")
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        pass
    try:
        thumb = make_thumbnail(cover_bytes, width)
    except Exception as e:
        current_app.logger.warning(f"Could not thumbnail cover of {book.filename}: {e}")
        return None
    try:
        os.makedirs(thumb_dir, exist_ok=True)
        # Drop thumbnails of older versions of this book's cover.
        for old in os.listdir(thumb_dir):
            current = f"{book.id}-{mtime}-"
            if old.startswith(f"{book.id}-") and not old.startswith(current):
                os.remove(os.path.join(thumb_dir, old))
        tmp = f"{path}.tmp"
        with open(tmp, "wb") as f:
            f.write(thumb)
        os.replace(tmp, path)
    except OSError as e:
        current_app.logger.warning(f"Could not cache thumbnail {path}: {e}")
    return thumb


@index_blueprint.route("/download/<filename>")
def download(filename):
    """Serve the EPUB file for download, respecting per-book access level."""
    book = get_book_or_404(filename)

    if not user_can_access_book(book):
        return jsonify({"error": "Forbidden"}), 403

    return send_from_directory(
        current_app.config["BOOK_DIR"], filename, as_attachment=True
    )


@index_blueprint.route("/book/<filename>", methods=["DELETE"])
@json_admin_required
def delete_book(filename):
    """Move a book to the trash. The row and EPUB stay put so the delete can be
    undone (POST /book/<filename>/restore); purge_trash() removes them for good
    after TRASH_RETENTION_DAYS."""
    book = get_book_or_404(filename)
    with commit_or_rollback():
        book.deleted_at = _utcnow()
    purge_trash()
    return jsonify({"message": "Moved to trash", "title": book.title})


@index_blueprint.route("/book/<filename>/restore", methods=["POST"])
@json_admin_required
def restore_book(filename):
    """Undo a delete."""
    book = get_book_or_404(filename, include_deleted=True)
    with commit_or_rollback():
        book.deleted_at = None
    return jsonify({"message": "Restored", "title": book.title})


def purge_trash(retention_days=None):
    """Permanently remove books that have been in the trash longer than the
    retention window — DB row, join-table rows, and the EPUB file. Returns
    the number purged."""
    if retention_days is None:
        retention_days = current_app.config.get("TRASH_RETENTION_DAYS", 30)
    # SQLite hands back naive datetimes, so compare against a naive UTC cutoff.
    cutoff = (_utcnow() - timedelta(days=retention_days)).replace(tzinfo=None)
    expired = Book.query.filter(
        Book.deleted_at.isnot(None), Book.deleted_at < cutoff
    ).all()
    for book in expired:
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
                current_app.logger.warning(
                    f"Purged DB row but failed to unlink {epub_path}: {e}"
                )
    return len(expired)


@index_blueprint.route("/books", methods=["GET"])
@json_login_required
def search_books():
    """Fuzzy title+author lookup. Answers "do I already own this scanned book?" —
    returns the closest library books (best first) so the app can show ownership
    without exact-string luck. Matching tolerates edition/format and name-order
    differences; the cutoff is LIBRARY_MATCH_THRESHOLD.
    """
    title = (request.args.get("title") or "").strip()
    author = (request.args.get("author") or "").strip()
    if not title and not author:
        return jsonify({"error": "title or author is required"}), 400

    query = Book.query.filter(Book.deleted_at.is_(None))
    if current_user.role == UserRoleChoice.STANDARD:
        query = query.filter(Book.access_level == AccessLevelChoice.STANDARD.value)

    threshold = current_app.config.get(
        "LIBRARY_MATCH_THRESHOLD", DEFAULT_MATCH_THRESHOLD
    )
    matches = rank_matches(title, author, query.all(), threshold)
    return jsonify({
        "matches": [
            {
                "title": book.title,
                "author": book.author,
                "filename": book.filename,
                "score": round(score, 3),
            }
            for book, score in matches
        ]
    })
