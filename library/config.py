import os

# Project root, one level above the library package.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DATA_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    # Loaded from the environment; create_app() raises if missing in non-test
    # contexts so we never silently fall back to a known-public key.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Database configuration
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "library.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Compression configuration
    COMPRESS_ALGORITHM = "gzip"  # or 'br' for Brotli
    COMPRESS_MIMETYPES = [
        "text/html",
        "text/css",
        "application/javascript",
        "application/json",
        "application/x-ndjson",
        "image/svg+xml",
    ]

    # Book directory
    BOOK_DIR = os.getenv("BOOK_DIR", os.path.join(BASE_DIR, "books"))

    # When set (e.g. "X-Forwarded-User"), trust the dashboard nginx header instead of
    # Flask-Login sessions. Unset for standalone dev / step-4 routing tests.
    AUTH_PROXY_HEADER = os.environ.get("AUTH_PROXY_HEADER") or None

    # Subpath mount behind nginx (e.g. "/library"). Empty/unset = served at "/".
    _app_root = os.environ.get("APPLICATION_ROOT", "").strip()
    APPLICATION_ROOT = _app_root if _app_root else "/"
