from flask import Flask, render_template, request, jsonify, send_from_directory
import logging
import os
from utils import get_epub_cover, get_epub_content

app = Flask(__name__)
 
BOOK_DIR = "static/"
# BOOK_DIR = "/mnt/backup/books"  # Directory where books are stored
 
def get_covers(offset=0, limit=10):
    """Returns a list of EPUB filenames and their associated cover image paths."""
    books = [f for f in os.listdir(BOOK_DIR) if not f.startswith(".") and f.endswith(('epub'))][offset:offset+limit]
    return [{"filename": book, "cover": get_epub_cover(os.path.join(BOOK_DIR, book))} for book in books]
 
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
def load_book(filename):
    try:
        book_data = get_epub_content(BOOK_DIR, filename)
        logging.info(f"Successfully processed book with {book_data['image_count']} images")
        return jsonify(book_data)
    except Exception as e:
        logging.error(f"Error processing epub: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download(filename):
    """Serve the EPUB file for download."""
    return send_from_directory(BOOK_DIR, filename, as_attachment=True)
 
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8002)
