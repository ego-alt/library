import logging
import os

import click
from ebooklib import epub
from flask import current_app
from flask.cli import with_appcontext

from .choices import UserRoleChoice
from .models import Book, User, db
from .utils import extract_metadata, get_epub_cover_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_book_dir(directory: str | None) -> str:
    book_dir = directory or current_app.config["BOOK_DIR"]
    return os.path.abspath(book_dir)


@click.command("import-books")
@click.option("--directory", help="Directory containing EPUB files")
@click.option(
    "--access-level", default="standard", help="Default access level for imported books"
)
@with_appcontext
def import_books_command(directory, access_level):
    """Import books from the specified directory."""
    book_dir = _resolve_book_dir(directory)

    if not os.path.isdir(book_dir):
        logger.error(f"Directory {book_dir} does not exist")
        return

    success_count = 0
    error_count = 0
    skip_count = 0

    for filename in os.listdir(book_dir):
        if not filename.endswith(".epub"):
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
            epub_book = epub.read_epub(full_path, options={"ignore_ncx": True})
            metadata = extract_metadata(epub_book)

            if metadata:
                # Get cover path within the epub
                cover_path = get_epub_cover_path(full_path)

                # Create new book record
                book = Book(
                    title=metadata["title"],
                    author=metadata["author"],
                    filename=filename,
                    cover_path=cover_path,  # Store the path within the epub
                    access_level=access_level,
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


@click.command("create-user")
@click.argument("username")
@click.argument("password")
@click.option(
    "--role",
    default="standard",
    type=click.Choice(["admin", "standard"], case_sensitive=False),
    help="User role (admin or standard) [default: standard]",
)
def create_user_command(username, password, role):
    """Create a new user."""
    user = User(username=username)
    user.set_password(password)
    user.role = UserRoleChoice(role.lower())
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created user: {username} with role {user.role.value}")


@click.command("refresh-cover-paths")
@with_appcontext
def refresh_cover_paths_command():
    """Re-scan each EPUB and update ``books.cover_path`` from the package document.

    Use after upgrading cover discovery or if covers fail due to stale paths in
    the database. Requires BOOK_DIR (or mount) to contain the files.
    """
    book_dir = current_app.config["BOOK_DIR"]
    updated = 0
    errors = 0
    for book in Book.query.all():
        full_path = os.path.join(book_dir, book.filename)
        if not os.path.isfile(full_path):
            logger.warning("refresh-cover-paths: missing file %s", full_path)
            errors += 1
            continue
        try:
            new_path = get_epub_cover_path(full_path)
        except Exception as e:
            logger.error("refresh-cover-paths: %s: %s", book.filename, e)
            errors += 1
            continue
        if book.cover_path != new_path:
            book.cover_path = new_path
            updated += 1
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("refresh-cover-paths commit failed: %s", e)
        raise
    click.echo(f"Updated cover_path for {updated} book(s). {errors} skipped (errors/missing files).")


def init_commands(app):
    """Register CLI commands."""
    app.cli.add_command(import_books_command)
    app.cli.add_command(create_user_command)
    app.cli.add_command(refresh_cover_paths_command)
