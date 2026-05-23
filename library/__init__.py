import logging
import os

from flask import Flask, jsonify, request
from flask_caching import Cache
from flask_compress import Compress
from flask_login import LoginManager
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .commands import init_commands
from .config import DATA_DIR, Config
from .models import db
from .proxy_auth import load_user_from_proxy_header
from .routes import (
    auth_blueprint,
    index_blueprint,
    metadata_blueprint,
    read_blueprint,
    upload_blueprint,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

cache = Cache(config={"CACHE_TYPE": "flask_caching.backends.simplecache.SimpleCache"})

BOOK_DIR_SENTINEL = ".library-mount"


def _verify_book_dir(book_dir: str) -> None:
    """Refuse to boot unless BOOK_DIR exists and carries the mount sentinel.

    Previously, create_app() auto-created BOOK_DIR with exist_ok=True. When the
    Pi's external drive failed to mount, that turned a hard error into a silent
    empty directory — and the old flush-books CLI then treated every row as
    orphaned and wiped the database. The sentinel is positive proof the right
    disk is mounted here; if it's absent, fail loud at boot.
    """
    if not os.path.isdir(book_dir):
        raise RuntimeError(
            f"BOOK_DIR does not exist: {book_dir}. "
            f"Create the directory and `touch {book_dir}/{BOOK_DIR_SENTINEL}` "
            "to confirm it's the right location."
        )

    sentinel = os.path.join(book_dir, BOOK_DIR_SENTINEL)
    if not os.path.isfile(sentinel):
        raise RuntimeError(
            f"Missing mount sentinel: {sentinel}. "
            "This file proves BOOK_DIR is your real library mount (not a "
            "freshly-created stub from a failed mount). If this IS your "
            f"library directory, run `touch {sentinel}` once to confirm."
        )


def create_app(config_overrides: dict | None = None):
    app = Flask(__name__)
    Compress(app)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    # Prefer a SECRET_KEY from the environment. If one isn't set, fall back to
    # a random per-process key so the app still boots — but warn loudly because
    # sessions won't survive a restart in that mode.
    if not app.config.get("SECRET_KEY"):
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret-key"
        else:
            import secrets
            app.config["SECRET_KEY"] = secrets.token_hex(32)
            logger.warning(
                "SECRET_KEY env var is not set; generated a random key for "
                "this process. Sessions will be invalidated on every restart. "
                "Set SECRET_KEY in your environment to persist sessions."
            )

    os.makedirs(DATA_DIR, exist_ok=True)
    if not app.config.get("TESTING"):
        _verify_book_dir(app.config["BOOK_DIR"])
    cache.init_app(app)

    # Honor X-Forwarded-* from nginx when TLS terminates upstream. x_prefix
    # picks up X-Forwarded-Prefix so url_for() emits the /library mount path.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    @app.get("/healthz")
    def healthz():
        return "", 200

    @app.after_request
    def add_cache_headers(response):
        if "/static/" in request.path:
            # Short cache so JS/CSS edits show up after a normal refresh
            # rather than a hard refresh.
            response.cache_control.max_age = 60
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return jsonify({"error": e.description}), e.code

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        from .models import User

        return db.session.get(User, int(user_id))

    @login_manager.request_loader
    def load_user_from_request(_request):
        return load_user_from_proxy_header()

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(index_blueprint)
    app.register_blueprint(metadata_blueprint)
    app.register_blueprint(read_blueprint)
    app.register_blueprint(upload_blueprint)

    db.init_app(app)
    Migrate(app, db, render_as_batch=True)
    init_commands(app)

    return app
