import logging
import os
from datetime import datetime

from ebooklib import epub
from flask import Flask, render_template, request, jsonify, send_from_directory, current_app
from flask_caching import Cache
from flask_compress import Compress
from flask_login import LoginManager, current_user

from config import Config
from commands import init_commands
from models import db, Book, Tag, User, book_tags, Bookmark, ProgressChoice
from routes import auth_blueprint, index_blueprint, metadata_blueprint, read_blueprint, upload_blueprint
from tag_manager import TagManager
from utils import get_epub_cover, get_epub_content, get_epub_cover_path, extract_metadata

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialise the app cache
cache = Cache(config={'CACHE_TYPE': 'simple'})

def create_app():
    app = Flask(__name__)
    Compress(app)
    app.config.from_object(Config)
    cache.init_app(app)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # @app.after_request
    # def add_cache_headers(response):
    #     response.cache_control.public = True
    #     response.cache_control.max_age = 3600  # Cache for 1 hour
    #     return response

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

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8002)
