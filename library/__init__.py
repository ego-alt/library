import logging
import os

from flask import Flask, jsonify, request
from flask_caching import Cache
from flask_compress import Compress
from flask_login import LoginManager
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException

from .commands import init_commands
from .config import Config, DATA_DIR
from .models import User, db
from .routes import (
    auth_blueprint,
    index_blueprint,
    metadata_blueprint,
    read_blueprint,
    upload_blueprint,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

cache = Cache(config={"CACHE_TYPE": "simple"})


def create_app():
    app = Flask(__name__)
    Compress(app)
    app.config.from_object(Config)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(app.config["BOOK_DIR"], exist_ok=True)
    cache.init_app(app)

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
        return User.query.get(int(user_id))

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(index_blueprint)
    app.register_blueprint(metadata_blueprint)
    app.register_blueprint(read_blueprint)
    app.register_blueprint(upload_blueprint)

    db.init_app(app)
    Migrate(app, db, render_as_batch=True)
    init_commands(app)

    return app
