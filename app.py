import logging
import os
from flask import Flask, request
from flask_caching import Cache
from flask_compress import Compress
from flask_login import LoginManager

from config import Config
from commands import init_commands
from models import db, User
from routes import (
    auth_blueprint,
    index_blueprint,
    metadata_blueprint,
    read_blueprint,
    upload_blueprint,
)

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialise the app cache
cache = Cache(config={"CACHE_TYPE": "simple"})


def create_app():
    app = Flask(__name__)
    Compress(app)
    app.config.from_object(Config)
    cache.init_app(app)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(index_blueprint)
    app.register_blueprint(metadata_blueprint)
    app.register_blueprint(read_blueprint)
    app.register_blueprint(upload_blueprint)

    # Initialize database
    db.init_app(app)
    # Register CLI commands
    init_commands(app)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=8002)
