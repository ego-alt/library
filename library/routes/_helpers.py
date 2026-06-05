from contextlib import contextmanager
from functools import wraps

from flask import abort, jsonify
from flask_login import current_user

from ..choices import AccessLevelChoice, UserRoleChoice
from ..models import Book, db


def json_login_required(view):
    """Like @login_required, but returns 401 JSON instead of redirecting."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        return view(*args, **kwargs)

    return wrapper


def json_admin_required(view):
    """Require an authenticated admin; respond with JSON 401/403 otherwise."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        if current_user.role != UserRoleChoice.ADMIN:
            return jsonify({"error": "Admin role required"}), 403
        return view(*args, **kwargs)

    return wrapper


def get_book_or_404(filename: str) -> Book:
    """Resolve a book by filename or abort with a JSON 404."""
    book = Book.query.filter_by(filename=filename).first()
    if not book:
        abort(404, description="Book not found")
    return book


def user_can_access_book(book: Book) -> bool:
    """Whether the current user may see/read/download this book. Standard-access
    books are open to everyone; anything else is admin-only."""
    if book.access_level == AccessLevelChoice.STANDARD.value:
        return True
    return current_user.is_authenticated and current_user.role == UserRoleChoice.ADMIN


@contextmanager
def commit_or_rollback():
    """Commit on success, roll back and re-raise on failure."""
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
