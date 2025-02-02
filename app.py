from auth import auth as auth_blueprint
from commands import init_commands
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, current_app
from flask_caching import Cache
from flask_compress import Compress
from flask_login import LoginManager, current_user
from ebooklib import epub

import logging
from models import db, Book, Tag, User, book_tags, Bookmark  # Add this import
import os
from utils import get_epub_cover, get_epub_content, get_epub_cover_path, extract_metadata


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Initialise the app cache
cache = Cache(config={'CACHE_TYPE': 'simple'})


def create_app():
    app = Flask(__name__)
    Compress(app)
    cache.init_app(app)

    app.config['SECRET_KEY'] = 'your-secret-key-here'
    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['COMPRESS_ALGORITHM'] = 'gzip'  # or 'br' for Brotli
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html',
        'text/css',
        'application/javascript',
        'application/json',
        'image/svg+xml'
    ]
    
    # Book directory configuration
    app.config['BOOK_DIR'] = os.getenv('BOOK_DIR', 'static/')
    # TODO: change to BOOK_DIR = "/mnt/backup/books"
 
    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Register blueprints 
    app.register_blueprint(auth_blueprint)

    def get_covers(offset=0, limit=10, filters=None):
        query = Book.query
        
        if filters:
            # Title filter - match any word
            if filters.get('title'):
                title_words = filters['title'].split()
                for word in title_words:
                    query = query.filter(Book.title.ilike(f'%{word}%'))
            
            # Author filter - match any word
            if filters.get('author'):
                author_words = filters['author'].split()
                for word in author_words:
                    query = query.filter(Book.author.ilike(f'%{word}%'))
            
            # Genre filter
            if filters.get('genre'):
                genre_words = filters['genre'].split()
                for word in genre_words:
                    query = query.filter(Book.genre.ilike(f'%{word}%'))
            
            # Tags filter - exact matches only for authenticated users
            if filters.get('tags'):
                logging.info(f"Tags filter: {filters['tags']}")
                if not current_user.is_authenticated:
                    return []

                tag_words = filters['tags'].split(",")
                tag_filters = [db.and_(
                    Tag.name == tag_name,
                    Tag.user_id == current_user.id
                ) for tag_name in tag_words]

                query = query.join(Book.tags).join(Tag.user).filter(db.or_(*tag_filters))
        
        books = query.offset(offset).limit(limit).all()
        return [{
            "filename": book.filename, 
            "cover": get_epub_cover(
                os.path.join(app.config['BOOK_DIR'], book.filename),
                book.cover_path
            )
        } for book in books]
 
    @app.route('/')
    def index():
        """Render the initial page with the first batch of book covers."""
        images = get_covers(0, 10)
        return render_template('index.html', images=images)
 
    @app.route('/load_more/<int:offset>', methods=['GET'])
    def load_more(offset):
        filters = {
            'title': request.args.get('title'),
            'author': request.args.get('author'),
            'genre': request.args.get('genre'),
            'tags': request.args.get('tags')
        }
        # Remove empty filters
        filters = {k: v for k, v in filters.items() if v}
        images = get_covers(offset, 10, filters)
        return jsonify(images)

    @app.route('/read/<filename>')
    def read_book(filename):
        """Render the reader page."""
        return render_template('reader.html')

    @app.route('/load_book/<filename>')
    @cache.cached(timeout=3600)
    def load_book(filename):
        try:
            book_data = get_epub_content(app.config['BOOK_DIR'], filename)
            logging.info(f"Successfully processed book with {book_data['image_count']} images")
            return jsonify(book_data)
        except Exception as e:
            logging.error(f"Error processing epub: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/download/<filename>')
    def download(filename):
        """Serve the EPUB file for download."""
        return send_from_directory(app.config['BOOK_DIR'], filename, as_attachment=True)

    @app.route('/book_metadata/<filename>', methods=['GET', 'POST'])
    def book_metadata(filename):
        book = Book.query.filter_by(filename=filename).first()
        if not book:
            return jsonify({'error': 'Book not found'}), 404
        
        if request.method == 'POST':
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401

            data = request.get_json()
            book.title = data.get('title', book.title)
            book.author = data.get('author', book.author)
            book.genre = data.get('genre', book.genre)
            try:
                # First, remove all existing tags for this user and book
                db.session.execute(
                    book_tags.delete().where(
                        db.and_(
                            book_tags.c.book_id == book.id,
                            book_tags.c.user_id == current_user.id
                        )
                    )
                )
                # Create/get tags and commit them
                for tag_name in data.get('tags', []):
                    tag = Tag.query.filter_by(
                        name=tag_name,
                        user_id=current_user.id
                    ).first()
                    
                    if not tag:
                        tag = Tag(name=tag_name, user_id=current_user.id)
                        db.session.add(tag)
                        db.session.flush()  # This assigns the ID without committing
                    
                    db.session.execute(
                        book_tags.insert().values(
                            book_id=book.id,
                            tag_id=tag.id,
                            user_id=current_user.id
                        )
                    )
                db.session.commit()
                return jsonify({'message': 'Metadata updated successfully'})
            except Exception as e:
                db.session.rollback()
                return jsonify({'error': str(e)}), 500
        
        # GET request handling
        response = {
            'title': book.title,
            'author': book.author,
            'genre': book.genre,
            'created_at': book.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'tags': [],
            'filename': book.filename,
            'cover': get_epub_cover(
                os.path.join(app.config['BOOK_DIR'], book.filename),
                book.cover_path
            )
        }
        
        # Only include tags if user is authenticated
        if current_user.is_authenticated:
            # Get tags specific to this user and book
            user_tags = db.session.query(Tag.name).join(
                book_tags,
                db.and_(
                    book_tags.c.tag_id == Tag.id,
                    book_tags.c.book_id == book.id,
                    book_tags.c.user_id == current_user.id
                )
            ).order_by(Tag.status).all()
            response['tags'] = [tag[0] for tag in user_tags]
        
        return jsonify(response)

    @app.route('/bookmark/<filename>', methods=['GET', 'POST'])
    def bookmark(filename):
        if not current_user.is_authenticated:
            return jsonify({'message': 'Authentication required.'}), 200
        
        book = Book.query.filter_by(filename=filename).first()
        if not book:
            return jsonify({'error': 'Book not found'}), 404
        
        if request.method == 'POST':
            data = request.get_json()
            bookmark = Bookmark.query.filter_by(
                user_id=current_user.id,
                book_id=book.id
            ).first()
            
            if not bookmark:
                bookmark = Bookmark(
                    user_id=current_user.id,
                    book_id=book.id
                )
                db.session.add(bookmark)
            
            bookmark.chapter_index = data.get('chapter_index', 0)
            bookmark.position = data.get('position', 0)
            bookmark.last_read = datetime.utcnow()
            
            try:
                db.session.commit()
                return jsonify({'message': 'Bookmark updated successfully'})
            except Exception as e:
                db.session.rollback()
                return jsonify({'error': str(e)}), 500
        
        # GET request - retrieve bookmark
        bookmark = Bookmark.query.filter_by(
            user_id=current_user.id,
            book_id=book.id
        ).first()
        
        if not bookmark:
            return jsonify({'chapter_index': 0, 'position': 0})
        
        return jsonify({
            'chapter_index': bookmark.chapter_index,
            'position': bookmark.position
        })

    @app.route('/tag_finished/<filename>', methods=['POST'])
    def tag_finished(filename):
        """Tag the book as finished."""
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        
        book = Book.query.filter_by(filename=filename).first()
        if not book:
            return jsonify({'error': 'Book not found'}), 404
        
        finish_tag = Tag.query.filter_by(name='Finished', user_id=current_user.id).first()
        if not finish_tag:
            finish_tag = Tag(name='Finished', user_id=current_user.id, status=0)
            db.session.add(finish_tag)
            db.session.flush()

        if not db.session.query(book_tags).filter_by(
            book_id=book.id, tag_id=finish_tag.id, user_id=current_user.id
        ).first():
            db.session.execute(
                book_tags.insert().values(
                    book_id=book.id,
                    tag_id=finish_tag.id,
                    user_id=current_user.id
                )
            )
            db.session.commit()
        return jsonify({'message': 'Book tagged as finished'})

    @app.after_request
    def add_cache_headers(response):
        response.cache_control.public = True
        response.cache_control.max_age = 3600  # Cache for 1 hour
        return response

    @app.route('/upload_book', methods=['POST'])
    def upload_book():
        """Endpoint to save the uploaded EPUB and return pre-populated metadata."""
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        # Check for the file in the request
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Save the file to the BOOK_DIR
        file_path = os.path.join(current_app.config['BOOK_DIR'], file.filename)
        file.save(file_path)
        current_app.logger.info(f"Saved uploaded file to {file_path}")

        # Read the EPUB file to extract metadata
        try:
            epub_book = epub.read_epub(file_path)
        except Exception as e:
            current_app.logger.error(f"Failed to read EPUB file: {str(e)}")
            return jsonify({'error': 'Failed to read EPUB file: ' + str(e)}), 500

        metadata = extract_metadata(epub_book)
        if not metadata:
            metadata = {'title': '', 'author': ''}

        # Get cover image details
        cover_path = get_epub_cover_path(file_path)
        cover = get_epub_cover(file_path, cover_path)

        # Return the metadata plus file details
        return jsonify({
            'filename': file.filename,
            'title': metadata.get('title', ''),
            'author': metadata.get('author', ''),
            'cover': cover,
            'cover_path': cover_path
        })

    @app.route('/upload_book_metadata', methods=['POST'])
    def upload_book_metadata():
        """Endpoint to save metadata for a newly uploaded book (creating a new DB record)."""
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        data = request.get_json()
        original_filename = data.get('original_filename')
        new_filename = data.get('new_filename')
        if not new_filename:
            return jsonify({'error': 'Missing new filename'}), 400

        # Ensure this file is not already in the database
        existing_book = Book.query.filter_by(filename=new_filename).first()
        if existing_book:
            return jsonify({'error': 'Book with this filename already exists'}), 400

        # Define the original and new file paths
        original_filepath = os.path.join(current_app.config['BOOK_DIR'], original_filename)
        new_filepath = os.path.join(current_app.config['BOOK_DIR'], new_filename)

        # Rename the file
        try:
            os.rename(original_filepath, new_filepath)
            current_app.logger.info(f"Renamed file from {original_filepath} to {new_filepath}")
        except Exception as e:
            current_app.logger.error(f"Failed to rename file: {str(e)}")
            return jsonify({'error': 'Failed to rename file: ' + str(e)}), 500

        # Create a new Book record with the submitted metadata
        new_book = Book(
            title=data.get('title'),
            author=data.get('author'),
            genre=data.get('genre'),
            filename=new_filename,
            cover_path=data.get('cover_path'),
            access_level='standard'  # or any default you wish
        )
        db.session.add(new_book)
        try:
            db.session.commit()
            return jsonify({'message': 'Book added successfully'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # Initialize database
    db.init_app(app)
    
    # Register CLI commands
    init_commands(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8002)
