import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'instance')

class Config:
    SECRET_KEY = 'your-secret-key-here'

    # Database configuration
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(DATA_DIR, 'library.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Compression configuration
    COMPRESS_ALGORITHM = 'gzip'  # or 'br' for Brotli
    COMPRESS_MIMETYPES = [
        'text/html',
        'text/css',
        'application/javascript',
        'application/json',
        'image/svg+xml'
    ]

    # Book directory
    BOOK_DIR = os.getenv('BOOK_DIR', '/mnt/backup/books/')
