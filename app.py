from flask import Flask, render_template, request, jsonify, send_from_directory
import logging
import os
from utils import get_epub_cover, get_epub_content
from commands import init_commands
from models import db, Book, Tag, User, book_tags, Bookmark  # Add this import
from flask_login import LoginManager, current_user
from datetime import datetime

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
    
    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
    from auth import auth as auth_blueprint
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
            if filters.get('tags') and current_user.is_authenticated:
                tag_words = filters['tags'].split()
                for tag_name in tag_words:
                    query = query.join(Book.tags).join(Tag.user).filter(
                        db.and_(
                            Tag.name == tag_name,
                            Tag.user_id == current_user.id
                        )
                    )
        
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
            
            # Update book metadata
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
                
                # Create/get tags and commit them first
                tags_to_add = []
                for tag_name in data.get('tags', []):
                    tag = Tag.query.filter_by(
                        name=tag_name,
                        user_id=current_user.id
                    ).first()
                    
                    if not tag:
                        tag = Tag(name=tag_name, user_id=current_user.id)
                        db.session.add(tag)
                        db.session.flush()  # This assigns the ID without committing
                    
                    tags_to_add.append(tag)
                
                # Now create the associations
                for tag in tags_to_add:
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
            'tags': []
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
            ).all()
            response['tags'] = [tag[0] for tag in user_tags]
        
        return jsonify(response)

    @app.route('/bookmark/<filename>', methods=['GET', 'POST'])
    def bookmark(filename):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        
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

    # Initialize database
    db.init_app(app)
    
    # Register CLI commands
    init_commands(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8002)
