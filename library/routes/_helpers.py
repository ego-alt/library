import os
from contextlib import contextmanager
from functools import wraps

from flask import abort, current_app, jsonify, url_for
from flask_login import current_user

from ..choices import AccessLevelChoice, UserRoleChoice
from ..models import Book, Bookmark, BookProgressChoice, db
from ..utils import COVER_STYLE, book_style_subset, spine_chapter_sizes


def json_login_required(view):
    """Like @login_required, but returns 401 JSON instead of redirecting."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Sign in to do that."}), 401
        return view(*args, **kwargs)

    return wrapper


def json_admin_required(view):
    """Require an authenticated admin; respond with JSON 401/403 otherwise."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Sign in to do that."}), 401
        if current_user.role != UserRoleChoice.ADMIN:
            return jsonify({"error": "Only an admin can do that."}), 403
        return view(*args, **kwargs)

    return wrapper


def book_status(book_id: int, user_id: int) -> str:
    """A user's reading status for a book: Unread, In Progress or Finished."""
    bookmark = Bookmark.query.filter_by(book_id=book_id, user_id=user_id).first()
    return (bookmark.status if bookmark else BookProgressChoice.UNREAD).value


def get_book_or_404(filename: str, include_deleted: bool = False) -> Book:
    """Resolve a book by filename or abort with a JSON 404. Books in the trash
    (soft-deleted) count as missing unless `include_deleted` is set."""
    query = Book.query.filter_by(filename=filename)
    if not include_deleted:
        query = query.filter(Book.deleted_at.is_(None))
    book = query.first()
    if not book:
        abort(404, description="Book not found")
    return book


def book_mtime(book: Book) -> int | None:
    """The EPUB's mtime as an int, or None if the file is missing. Changes
    whenever the file is rewritten (e.g. a new cover), so it doubles as a
    version for cache-busting URLs."""
    try:
        path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
        return int(os.path.getmtime(path))
    except OSError:
        return None


def cover_url(book: Book, width: int | None = None) -> str:
    """Versioned cover URL, optionally a `width`-px thumbnail. /cover is cached
    for a year, so the ?v= must change when the cover does, or browsers keep
    showing the old one."""
    params = {}
    mtime = book_mtime(book)
    if mtime is not None:
        params["v"] = f"{mtime}.{COVER_STYLE}"   # a new fallback drawing is a new cover too
    if width:
        params["w"] = width
    if not book.cover_path:
        params["drawn"] = 1   # one we draw (utils.fallback_cover_svg), which night mode recolours
    return url_for("index_routes.cover", filename=book.filename, **params)


def chapter_sizes(book: Book) -> list[int]:
    """Cached per-chapter weights for whole-book progress (see
    utils.book_progress), keyed on (book id, file mtime)."""
    mtime = book_mtime(book)
    if mtime is None:
        return []

    # Local import to avoid circular import via library/__init__.py.
    from .. import cache

    key = f"chapter_sizes:{book.id}:{mtime}"
    sizes = cache.get(key)
    if sizes is None:
        try:
            path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
            sizes = spine_chapter_sizes(path)
        except Exception as e:
            current_app.logger.warning(f"Could not read spine of {book.filename}: {e}")
            sizes = []
        cache.set(key, sizes, timeout=86400)
    return sizes


def book_css(book: Book) -> str:
    """Cached structural styling for the reader (see utils.book_style_subset),
    keyed on (book id, file mtime)."""
    mtime = book_mtime(book)
    if mtime is None:
        return ""

    # Local import to avoid circular import via library/__init__.py.
    from .. import cache

    key = f"book_css:{book.id}:{mtime}"
    css = cache.get(key)
    if css is None:
        path = os.path.join(current_app.config["BOOK_DIR"], book.filename)
        css = book_style_subset(path)
        cache.set(key, css, timeout=86400)
    return css


def user_can_access_book(book: Book) -> bool:
    """Whether the current user may see/read/download this book. Standard-access
    books are open to everyone; anything else is admin-only."""
    if book.access_level == AccessLevelChoice.STANDARD.value:
        return True
    return current_user.is_authenticated and current_user.role == UserRoleChoice.ADMIN


def get_accessible_book_or_404(filename: str) -> Book:
    """``get_book_or_404`` for the current user: a book they may not access is
    reported as missing, so its existence doesn't leak either."""
    book = get_book_or_404(filename)
    if not user_can_access_book(book):
        abort(404, description="Book not found")
    return book


@contextmanager
def commit_or_rollback():
    """Commit on success, roll back and re-raise on failure."""
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
