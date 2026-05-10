import os
import sys

import pytest

# Ensure the project root is on sys.path so `from library import ...` works
# regardless of where pytest is invoked from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from library import create_app  # noqa: E402
from library.choices import UserRoleChoice  # noqa: E402
from library.models import Book, User, db  # noqa: E402

from tests._epub_builder import build_epub3  # noqa: E402


@pytest.fixture
def book_dir(tmp_path):
    """A throwaway directory used as BOOK_DIR for a single test."""
    d = tmp_path / "books"
    d.mkdir()
    return d


@pytest.fixture
def app(book_dir, monkeypatch):
    """A Flask app wired to an in-memory SQLite and a temp BOOK_DIR."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "BOOK_DIR": str(book_dir),
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def standard_user(app):
    user = User(username="standard", role=UserRoleChoice.STANDARD)
    user.set_password("pw")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(app):
    user = User(username="admin", role=UserRoleChoice.ADMIN)
    user.set_password("pw")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user_id):
    """Inject Flask-Login session cookie without going through /auth/login."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


@pytest.fixture
def standard_client(client, standard_user):
    _login(client, standard_user.id)
    return client


@pytest.fixture
def admin_client(client, admin_user):
    _login(client, admin_user.id)
    return client


@pytest.fixture
def sample_epub_bytes():
    """A minimal but valid EPUB3 with two chapters, a nav doc, and a cover."""
    return build_epub3()


@pytest.fixture
def book(app, book_dir, sample_epub_bytes):
    """A persisted Book row backed by a real EPUB file in the temp BOOK_DIR."""
    filename = "test_book.epub"
    (book_dir / filename).write_bytes(sample_epub_bytes)
    book = Book(
        title="Test Book",
        author="Test Author",
        filename=filename,
        cover_path="OEBPS/cover.png",
        access_level="standard",
    )
    db.session.add(book)
    db.session.commit()
    return book
