import click
from flask.cli import with_appcontext
import os
import ebooklib
from ebooklib import epub
from models import db, Book, User, Tag
import logging
from flask import current_app
from utils import get_epub_cover, get_epub_cover_path, extract_metadata
import base64
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.command('import-books')
@click.option('--directory', help='Directory containing EPUB files')
@click.option('--access-level', default='standard', help='Default access level for imported books')
@with_appcontext
def import_books_command(directory, access_level):
    """Import books from the specified directory."""
    # Use provided directory or fall back to BOOK_DIR from app config
    book_dir = directory or current_app.config['BOOK_DIR']
    
    if not os.path.exists(book_dir):
        logger.error(f"Directory {book_dir} does not exist")
        return

    success_count = 0
    error_count = 0
    skip_count = 0

    for filename in os.listdir(book_dir):
        if not filename.endswith('.epub'):
            continue

        full_path = os.path.join(book_dir, filename)
        
        # Check if book already exists
        existing_book = Book.query.filter_by(filename=filename).first()
        if existing_book:
            logger.info(f"Skipping {filename} - already in database")
            skip_count += 1
            continue

        try:
            # Read EPUB file
            epub_book = epub.read_epub(full_path)
            metadata = extract_metadata(epub_book)

            if metadata:
                # Get cover path within the epub
                cover_path = get_epub_cover_path(full_path)

                # Create new book record
                book = Book(
                    title=metadata['title'],
                    author=metadata['author'],
                    filename=filename,
                    cover_path=cover_path,  # Store the path within the epub
                    access_level=access_level
                )
                db.session.add(book)
                success_count += 1
                logger.info(f"Successfully imported: {filename}")
            else:
                error_count += 1
                logger.error(f"Could not extract metadata from {filename}")

        except Exception as e:
            error_count += 1
            logger.error(f"Error processing {filename}: {str(e)}")

    # Commit all changes
    try:
        db.session.commit()
        logger.info(f"""
Import completed:
- Successfully imported: {success_count} books
- Skipped (already exists): {skip_count} books
- Errors: {error_count} books
""")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing to database: {str(e)}")


@click.command('flush-books')
@click.option('--directory', help='Directory containing EPUB files')
@with_appcontext
def remove_deleted_books_command(directory):
    """Remove books from the database that no longer exist in the specified directory."""
    # Use provided directory or fall back to BOOK_DIR from app config
    book_dir = directory or current_app.config['BOOK_DIR']
    
    if not os.path.exists(book_dir):
        logger.error(f"Directory {book_dir} does not exist")
        return

    # Get all books from the database
    all_books = Book.query.all()
    deleted_count = 0

    for book in all_books:
        full_path = os.path.join(book_dir, book.filename)
        if not os.path.exists(full_path):
            # Book file does not exist, remove from database
            db.session.delete(book)
            deleted_count += 1
            logger.info(f"Deleted {book.filename} from database - file not found")

    # Commit all changes
    try:
        db.session.commit()
        logger.info(f"Removed {deleted_count} books from the database that no longer exist in {book_dir}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing to database: {str(e)}")


@click.command('create-user')
@click.argument('username')
@click.argument('password')
def create_user_command(username, password):
    """Create a new user."""
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    # Create default tags for the user
    in_progress_tag = Tag(name="In Progress", user_id=user.id, category=0)
    finish_tag = Tag(name="Finished", user_id=user.id, category=0)
    db.session.add(in_progress_tag)
    db.session.add(finish_tag)
    db.session.commit()
    
    click.echo(f'Created user: {username}')


def init_commands(app):
    """Register CLI commands."""
    app.cli.add_command(import_books_command)
    app.cli.add_command(remove_deleted_books_command)
    app.cli.add_command(create_user_command)