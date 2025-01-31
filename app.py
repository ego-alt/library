from flask import Flask, render_template, request, jsonify, send_from_directory
import logging
import os
from utils import get_epub_cover, get_epub_content
from commands import init_commands
from models import db, Book  # Add this import

def create_app():
    app = Flask(__name__)
    
    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Book directory configuration
    app.config['BOOK_DIR'] = os.getenv('BOOK_DIR', 'static/')
    # TODO: change to BOOK_DIR = "/mnt/backup/books"
 
    def get_covers(offset=0, limit=10, filters=None):
        query = Book.query
        # filters parameter is kept for future implementation
        
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
        images = get_covers(offset, 10)
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

    @app.route('/book_metadata/<filename>')
    def book_metadata(filename):
        book = Book.query.filter_by(filename=filename).first()
        if not book:
            return jsonify({'error': 'Book not found'}), 404
            
        return jsonify({
            'title': book.title,
            'author': book.author,
            'genre': book.genre,
            'created_at': book.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'tags': [tag.name for tag in book.tags]
        })
 
    # Initialize database
    db.init_app(app)
    
    # Register CLI commands
    init_commands(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8002)
